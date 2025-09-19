# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import xlsxwriter
import io
import base64
from datetime import datetime, date
import logging
from .report_helpers import ReportExporter

_logger = logging.getLogger(__name__)


class UniversalReportBuilder(models.Model):
    _name = 'universal.report.builder'
    _description = 'Конструктор звітів'
    _order = 'name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Назва звіту', required=True, translate=True)
    description = fields.Text('Опис', translate=True)

    model_id = fields.Many2one('ir.model', 'Модель даних', required=True,
                               domain=[('transient', '=', False)], ondelete='cascade')
    model_name = fields.Char(related='model_id.model', store=True, readonly=True)

    # Поля звіту
    field_ids = fields.One2many('universal.report.field', 'report_id',
                                string='Поля звіту')

    # Фільтри
    filter_ids = fields.One2many('universal.report.filter', 'report_id',
                                 string='Фільтри')

    # Групування
    group_ids = fields.One2many('universal.report.group', 'report_id',
                                string='Групування')

    # Сортування
    sort_ids = fields.One2many('universal.report.sort', 'report_id',
                               string='Сортування')

    # Налаштування звіту
    is_template = fields.Boolean('Шаблон звіту', default=False)
    format_type = fields.Selection([
        ('table', 'Таблиця'),
        ('pivot', 'Зведена таблиця'),
        ('chart', 'Графік'),
    ], string='Тип звіту', default='table')

    export_formats = fields.Selection([
        ('excel', 'Excel'),
        ('pdf', 'PDF'),
        ('csv', 'CSV'),
        ('html', 'HTML'),
    ], string='Формат експорту', default='excel')

    # Результати
    last_execution = fields.Datetime('Останнє виконання', readonly=True)
    result_count = fields.Integer('Кількість записів', readonly=True)
    execution_time = fields.Float('Час виконання (сек)', readonly=True)

    # Права доступу
    user_ids = fields.Many2many('res.users', 'report_builder_users_rel',
                                'report_id', 'user_id', string='Користувачі')
    group_ids_access = fields.Many2many('res.groups', 'report_builder_groups_rel',
                                        'report_id', 'group_id',
                                        string='Групи доступу')

    active = fields.Boolean('Активний', default=True)
    color = fields.Integer('Колір')

    # Примітка: При ondelete='cascade' звіти автоматично видаляються при видаленні моделі

    @api.constrains('field_ids')
    def _check_fields_exist(self):
        """Перевірка що є хоча б одне поле для відображення"""
        for record in self:
            if not record.field_ids.filtered('visible'):
                raise ValidationError(_('Повинно бути вибрано хоча б одне поле для відображення'))

    @api.model
    def get_model_fields(self, model_name):
        """Отримати поля моделі для конструктора"""
        if not model_name:
            return []

        try:
            model_obj = self.env[model_name]
        except KeyError:
            _logger.error(f"Модель {model_name} не знайдена")
            return []

        fields_data = []

        for field_name, field in model_obj._fields.items():
            # Пропускаємо службові поля
            if field_name.startswith('_') or field_name in ['id', 'create_uid', 'create_date', 'write_uid',
                                                            'write_date']:
                continue

            field_info = {
                'name': field_name,
                'string': field.string or field_name,
                'type': field.type,
                'required': field.required,
                'readonly': field.readonly,
                'relation': getattr(field, 'comodel_name', None),
                'selection': getattr(field, 'selection', None),
                'help': field.help or '',
            }
            fields_data.append(field_info)

        return sorted(fields_data, key=lambda x: x['string'])

    def execute_report(self, context_filters=None, limit=None):
        """Виконати звіт та отримати дані"""
        self.ensure_one()

        if not self.model_name:
            raise UserError(_('Не вказана модель даних'))

        if not self.field_ids.filtered('visible'):
            raise UserError(_('Не вибрані поля для звіту'))

        start_time = datetime.now()

        try:
            model_obj = self.env[self.model_name]

            # Побудова домену з фільтрів
            domain = self._build_domain(context_filters)
            _logger.info(f"Виконується звіт '{self.name}' з доменом: {domain}")

            # Отримання полів для вибірки
            fields_to_read = [f.field_name for f in self.field_ids if f.visible]

            # Виконання запиту з обмеженням
            if limit:
                records = model_obj.search(domain, limit=limit,
                                           order=self._get_order_string())
            else:
                records = model_obj.search(domain, order=self._get_order_string())

            # Читання даних
            if records:
                data = records.read(fields_to_read)

                # Застосування групування
                if self.group_ids:
                    data = self._apply_grouping(data, records)
            else:
                data = []

            # Оновлення статистики
            execution_time = (datetime.now() - start_time).total_seconds()
            self.write({
                'last_execution': fields.Datetime.now(),
                'result_count': len(data),
                'execution_time': execution_time
            })

            _logger.info(f"Звіт '{self.name}' виконано успішно. Записів: {len(data)}, час: {execution_time:.2f}с")
            return data

        except Exception as e:
            _logger.error(f"Помилка виконання звіту '{self.name}': {str(e)}")
            raise UserError(_('Помилка виконання звіту: %s') % str(e))

    def _build_domain(self, context_filters=None):
        """Побудувати домен з фільтрів"""
        domain = []

        # Фільтри з налаштувань звіту
        for filter_rec in self.filter_ids:
            if filter_rec.active:
                condition = self._build_filter_condition(filter_rec)
                if condition:
                    domain.append(condition)

        # Контекстні фільтри
        if context_filters:
            for filter_data in context_filters:
                if all(key in filter_data for key in ['field', 'operator', 'value']):
                    domain.append((filter_data['field'], filter_data['operator'], filter_data['value']))

        return domain

    def _build_filter_condition(self, filter_rec):
        """Побудувати умову фільтра"""
        field_name = filter_rec.field_name
        operator = filter_rec.operator
        value = filter_rec.value

        if not value and operator not in ('!=', 'not in'):
            return None

        # Обробка різних типів значень
        try:
            if filter_rec.field_type == 'many2one':
                if value and value.isdigit():
                    value = int(value)
                else:
                    return None
            elif filter_rec.field_type == 'boolean':
                value = value.lower() in ('true', '1', 'yes', 'так')
            elif filter_rec.field_type in ('integer', 'float'):
                value = float(value) if filter_rec.field_type == 'float' else int(value)
            elif filter_rec.field_type == 'date':
                if isinstance(value, str):
                    value = datetime.strptime(value, '%Y-%m-%d').date()
            elif filter_rec.field_type == 'datetime':
                if isinstance(value, str):
                    value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError) as e:
            _logger.warning(f"Помилка конвертації значення фільтра {field_name}: {e}")
            return None

        return (field_name, operator, value)

    def _get_order_string(self):
        """Отримати рядок сортування"""
        if not self.sort_ids:
            return 'id'

        order_parts = []
        for sort_field in self.sort_ids.sorted('sequence'):
            direction = 'DESC' if sort_field.direction == 'desc' else 'ASC'
            order_parts.append(f"{sort_field.field_name} {direction}")

        return ', '.join(order_parts)

    def _apply_grouping(self, data, records):
        """Застосувати групування до даних"""
        if not self.group_ids:
            return data

        # Просте групування по першому полю
        group_field = self.group_ids[0].field_name
        grouped_data = {}

        for record in data:
            group_key = record.get(group_field, _('Не визначено'))
            if isinstance(group_key, (list, tuple)) and len(group_key) > 1:
                group_key = group_key[1]  # Для many2one полів

            if group_key not in grouped_data:
                grouped_data[group_key] = []
            grouped_data[group_key].append(record)

        # Перетворення у список з групами
        result = []
        for group_key, group_records in grouped_data.items():
            result.append({
                'group_name': str(group_key),
                'group_count': len(group_records),
                'records': group_records
            })

        return result

    def export_to_excel(self, data=None):
        """Експорт звіту в Excel"""
        if data is None:
            data = self.execute_report()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Створення стилів
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })

        cell_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter'
        })

        number_format = workbook.add_format({
            'border': 1,
            'align': 'right',
            'num_format': '#,##0.00'
        })

        # Створення листа
        worksheet = workbook.add_worksheet(self.name[:31])

        # Заголовки
        visible_fields = self.field_ids.filtered('visible').sorted('sequence')
        headers = [f.field_label or f.field_name for f in visible_fields]

        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
            worksheet.set_column(col, col, max(len(header) + 5, 15))

        # Дані
        row = 1
        if isinstance(data, list) and data and 'group_name' in data[0]:
            # Групировані дані
            group_format = workbook.add_format({
                'bold': True,
                'bg_color': '#D9E2F3',
                'border': 1
            })

            for group in data:
                # Заголовок групи
                worksheet.merge_range(row, 0, row, len(headers) - 1,
                                      f"{group['group_name']} ({group['group_count']} записів)",
                                      group_format)
                row += 1

                # Записи групи
                for record in group['records']:
                    for col, field in enumerate(visible_fields):
                        value = record.get(field.field_name, '')
                        if isinstance(value, (list, tuple)) and len(value) > 1:
                            value = value[1]  # Для many2one полів

                        cell_fmt = number_format if field.field_type in ('integer', 'float',
                                                                         'monetary') else cell_format
                        worksheet.write(row, col, value or '', cell_fmt)
                    row += 1
                row += 1  # Порожній рядок між групами
        else:
            # Звичайні дані
            for record in data:
                for col, field in enumerate(visible_fields):
                    value = record.get(field.field_name, '')
                    if isinstance(value, (list, tuple)) and len(value) > 1:
                        value = value[1]  # Для many2one полів

                    cell_fmt = number_format if field.field_type in ('integer', 'float', 'monetary') else cell_format
                    worksheet.write(row, col, value or '', cell_fmt)
                row += 1

        workbook.close()
        output.seek(0)

        return base64.b64encode(output.read())

    def action_execute_report(self):
        """Дія виконання звіту"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Результат: %s') % self.name,
            'res_model': 'universal.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_report_id': self.id,
                'default_export_format': 'preview'
            }
        }

    def action_duplicate(self):
        """Створити копію звіту"""
        copy_name = _("%s (копія)") % self.name
        new_report = self.copy({'name': copy_name, 'is_template': False})

        return {
            'type': 'ir.actions.act_window',
            'name': _('Новий звіт'),
            'res_model': 'universal.report.builder',
            'res_id': new_report.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_scheduler(self):
        """Створити планувальник для звіту"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Планувальник звітів'),
            'res_model': 'universal.report.scheduler',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_report_id': self.id}
        }

    def export_to_pdf(self, data):
        exporter = ReportExporter(self, data)
        return base64.b64encode(exporter.to_pdf())