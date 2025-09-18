# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging
import base64

_logger = logging.getLogger(__name__)


class UniversalReportScheduler(models.Model):
    _name = 'universal.report.scheduler'
    _description = 'Планувальник звітів'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Назва завдання', required=True, translate=True)
    description = fields.Text('Опис', translate=True)
    report_id = fields.Many2one('universal.report.builder', string='Звіт',
                                required=True, ondelete='cascade')

    # Налаштування розкладу
    active = fields.Boolean('Активний', default=True)
    interval_type = fields.Selection([
        ('minutes', 'Хвилини'),
        ('hours', 'Години'),
        ('days', 'Дні'),
        ('weeks', 'Тижні'),
        ('months', 'Місяці'),
    ], string='Інтервал', default='days', required=True)
    interval_number = fields.Integer('Кожні', default=1, required=True)

    # Час виконання
    execution_time = fields.Float('Час виконання', default=9.0,
                                  help='Година виконання (наприклад, 9.5 = 09:30)')
    weekday = fields.Selection([
        ('0', 'Понеділок'),
        ('1', 'Вівторок'),
        ('2', 'Середа'),
        ('3', 'Четвер'),
        ('4', 'П\'ятниця'),
        ('5', 'Субота'),
        ('6', 'Неділя'),
    ], string='День тижня')

    # Умови виконання
    filter_values = fields.Text('Значення фільтрів (JSON)',
                                help='JSON з налаштуваннями фільтрів')
    max_records = fields.Integer('Максимум записів', default=1000,
                                 help='Обмеження кількості записів у звіті')

    # Сповіщення
    email_recipients = fields.Text('Email отримувачі',
                                   help='Список email адрес (по одній на рядок)')
    email_subject = fields.Char('Тема листа', translate=True)
    email_body = fields.Html('Текст листа', translate=True)
    attach_report = fields.Boolean('Прикріпити звіт', default=True)
    attach_format = fields.Selection([
        ('excel', 'Excel'),
        ('pdf', 'PDF'),
        ('csv', 'CSV'),
    ], string='Формат файлу', default='excel')

    # Статистика
    last_execution = fields.Datetime('Останнє виконання', readonly=True)
    next_execution = fields.Datetime('Наступне виконання', readonly=True)
    execution_count = fields.Integer('Кількість виконань', default=0, readonly=True)
    last_error = fields.Text('Остання помилка', readonly=True)

    # Пов'язане завдання cron
    cron_id = fields.Many2one('ir.cron', string='Завдання Cron', readonly=True)

    # Налаштування збереження
    auto_cleanup = fields.Boolean('Автоочищення', default=True,
                                  help='Автоматично видаляти старі файли')
    cleanup_days = fields.Integer('Зберігати днів', default=30)

    @api.constrains('interval_number')
    def _check_interval_number(self):
        """Перевірка що інтервал більше 0"""
        for record in self:
            if record.interval_number <= 0:
                raise ValidationError(_('Інтервал повинен бути більше 0'))

    @api.constrains('execution_time')
    def _check_execution_time(self):
        """Перевірка коректності часу виконання"""
        for record in self:
            if not (0 <= record.execution_time < 24):
                raise ValidationError(_('Час виконання повинен бути між 0 та 24 годинами'))

    @api.model
    def create(self, vals):
        """Створення завдання з автоматичним створенням cron"""
        if not vals.get('email_subject'):
            report_name = vals.get('report_id') and self.env['universal.report.builder'].browse(
                vals['report_id']).name or ''
            vals['email_subject'] = _('Звіт: %s') % report_name

        if not vals.get('email_body'):
            vals['email_body'] = _('''
                <p>Автоматично згенерований звіт.</p>
                <p>Дата виконання: <strong>%(date)s</strong></p>
                <p>З найкращими побажаннями,<br/>Система звітності</p>
            ''')

        record = super().create(vals)
        if record.active:
            record._create_cron_job()
        return record

    def write(self, vals):
        """Оновлення з пересозданням cron"""
        res = super().write(vals)
        if any(field in vals for field in ['interval_type', 'interval_number',
                                           'execution_time', 'weekday', 'active']):
            for record in self:
                record._create_cron_job()
        return res

    def unlink(self):
        """Видалення з очищенням cron"""
        for record in self:
            if record.cron_id:
                record.cron_id.unlink()
        return super().unlink()

    def _create_cron_job(self):
        """Створити або оновити завдання cron"""
        self.ensure_one()

        if self.cron_id:
            self.cron_id.unlink()

        if not self.active:
            self.cron_id = False
            return

        # Розрахунок наступного виконання
        next_call = self._calculate_next_execution()

        # Створення нового завдання cron
        cron_vals = {
            'name': f'Звіт: {self.name}',
            'model_id': self.env.ref('universal_reports.model_universal_report_scheduler').id,
            'code': f'model.browse({self.id}).execute_scheduled_report()',
            'active': True,
            'interval_type': self.interval_type,
            'interval_number': self.interval_number,
            'numbercall': -1,  # Нескінченно
            'nextcall': next_call,
            'doall': False,
        }

        # Додаткові налаштування для тижневого розкладу
        if self.interval_type == 'weeks' and self.weekday:
            cron_vals['weekday'] = self.weekday

        self.cron_id = self.env['ir.cron'].create(cron_vals)
        self.next_execution = next_call

    def _calculate_next_execution(self):
        """Розрахувати наступний час виконання"""
        now = datetime.now()
        hour = int(self.execution_time)
        minute = int((self.execution_time - hour) * 60)

        if self.interval_type == 'minutes':
            return now + timedelta(minutes=self.interval_number)
        elif self.interval_type == 'hours':
            return now + timedelta(hours=self.interval_number)
        elif self.interval_type == 'days':
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            return next_run
        elif self.interval_type == 'weeks':
            # Знайти наступний день тижня
            target_weekday = int(self.weekday) if self.weekday else 0
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:  # Цільовий день уже пройшов цього тижня
                days_ahead += 7
            next_run = now + timedelta(days=days_ahead)
            return next_run.replace(hour=hour, minute=minute, second=0, microsecond=0)
        elif self.interval_type == 'months':
            # Перший день наступного місяця
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)
            return next_month.replace(hour=hour, minute=minute, second=0, microsecond=0)

        return now + timedelta(days=1)

    def execute_scheduled_report(self):
        """Виконати запланований звіт"""
        self.ensure_one()

        try:
            _logger.info(f"Починається виконання запланованого звіту: {self.name}")

            # Підготовка фільтрів
            context_filters = []
            if self.filter_values:
                try:
                    import json
                    context_filters = json.loads(self.filter_values)
                except json.JSONDecodeError:
                    _logger.warning(f"Неможливо розпарсити фільтри для звіту {self.name}")

            # Виконання звіту з обмеженням
            data = self.report_id.execute_report(
                context_filters=context_filters,
                limit=self.max_records
            )

            # Відправка по email якщо налаштовано
            if self.email_recipients and self.attach_report:
                self._send_report_email(data)

            # Оновлення статистики
            self.write({
                'last_execution': fields.Datetime.now(),
                'execution_count': self.execution_count + 1,
                'last_error': False,
                'next_execution': self._calculate_next_execution()
            })

            # Автоочищення
            if self.auto_cleanup:
                self._cleanup_old_files()

            _logger.info(f"Звіт {self.name} успішно виконано. Записів: {len(data)}")

        except Exception as e:
            error_msg = f"Помилка виконання звіту {self.name}: {str(e)}"
            _logger.error(error_msg)

            self.write({
                'last_error': error_msg,
                'last_execution': fields.Datetime.now()
            })

            # Сповіщення про помилку
            if self.email_recipients:
                self._send_error_notification(error_msg)

    def _send_report_email(self, data):
        """Відправити звіт по email"""
        self.ensure_one()

        # Генерація файлу звіту
        if self.attach_format == 'excel':
            file_data = self.report_id.export_to_excel(data)
            filename = f'{self.report_id.name}.xlsx'
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        elif self.attach_format == 'csv':
            # TODO: Реалізувати експорт в CSV
            file_data = base64.b64encode(b'CSV export not implemented yet')
            filename = f'{self.report_id.name}.csv'
            mimetype = 'text/csv'
        else:  # PDF
            # TODO: Реалізувати експорт в PDF
            file_data = base64.b64encode(b'PDF export not implemented yet')
            filename = f'{self.report_id.name}.pdf'
            mimetype = 'application/pdf'

        # Створення вкладення
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': file_data,
            'mimetype': mimetype,
            'res_model': self._name,
            'res_id': self.id,
        })

        # Підготовка тексту листа
        body_html = self.email_body or ''
        body_html = body_html.replace('%(date)s', fields.Datetime.now().strftime('%d.%m.%Y %H:%M'))
        body_html = body_html.replace('%(records_count)s', str(len(data)))
        body_html = body_html.replace('%(report_name)s', self.report_id.name)

        # Відправка email
        email_to = self.email_recipients.replace('\n', ',').replace(';', ',')
        mail_values = {
            'subject': self.email_subject or _('Звіт: %s') % self.report_id.name,
            'body_html': body_html,
            'email_to': email_to,
            'attachment_ids': [(6, 0, [attachment.id])],
            'auto_delete': True,
        }

        mail = self.env['mail.mail'].create(mail_values)
        try:
            mail.send()
            _logger.info(f"Звіт {self.name} відправлено на {email_to}")
        except Exception as e:
            _logger.error(f"Помилка відправки email для звіту {self.name}: {e}")

    def _send_error_notification(self, error_msg):
        """Відправити сповіщення про помилку"""
        self.ensure_one()

        email_to = self.email_recipients.replace('\n', ',').replace(';', ',')
        mail_values = {
            'subject': _('ПОМИЛКА: Звіт %s') % self.report_id.name,
            'body_html': f'''
                <p>Виникла помилка при виконанні запланованого звіту.</p>
                <p><strong>Назва звіту:</strong> {self.report_id.name}</p>
                <p><strong>Час помилки:</strong> {fields.Datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
                <p><strong>Опис помилки:</strong></p>
                <pre>{error_msg}</pre>
                <p>Перевірте налаштування звіту та планувальника.</p>
            ''',
            'email_to': email_to,
            'auto_delete': True,
        }

        mail = self.env['mail.mail'].create(mail_values)
        try:
            mail.send()
        except Exception as e:
            _logger.error(f"Не вдалося відправити сповіщення про помилку: {e}")

    def _cleanup_old_files(self):
        """Очищення старих файлів"""
        if not self.cleanup_days:
            return

        cutoff_date = datetime.now() - timedelta(days=self.cleanup_days)
        old_attachments = self.env['ir.attachment'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('create_date', '<', cutoff_date)
        ])

        if old_attachments:
            count = len(old_attachments)
            old_attachments.unlink()
            _logger.info(f"Видалено {count} старих файлів для звіту {self.name}")

    def action_execute_now(self):
        """Виконати звіт зараз (ручний запуск)"""
        self.ensure_one()

        try:
            self.execute_scheduled_report()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Звіт успішно виконано'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Помилка виконання звіту: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_toggle_active(self):
        """Перемкнути активність планувальника"""
        for record in self:
            record.active = not record.active
            if record.active:
                record._create_cron_job()
            elif record.cron_id:
                record.cron_id.active = False