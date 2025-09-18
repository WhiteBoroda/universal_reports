# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import base64
import logging

_logger = logging.getLogger(__name__)


class UniversalReportWizard(models.TransientModel):
    _name = 'universal.report.wizard'
    _description = 'Майстер виконання звіту'

    report_id = fields.Many2one('universal.report.builder', string='Звіт',
                                required=True, readonly=True)
    export_format = fields.Selection([
        ('preview', 'Попередній перегляд'),
        ('excel', 'Excel'),
        ('pdf', 'PDF'),
        ('csv', 'CSV'),
        ('json', 'JSON'),
    ], string='Формат', default='preview', required=True)

    # Динамічні фільтри
    filter_values = fields.Text('Значення фільтрів (JSON)',
                                help='JSON з додатковими фільтрами')
    limit_records = fields.Integer('Обмежити записи', default=1000,
                                   help='Максимальна кількість записів для відображення')

    # Результати
    state = fields.Selection([
        ('draft', 'Підготовка'),
        ('executing', 'Виконання'),
        ('done', 'Завершено'),
        ('error', 'Помилка'),
    ], string='Статус', default='draft')

    result_data = fields.Text('Дані результату')
    result_file = fields.Binary('Файл результату')
    result_filename = fields.Char('Ім\'я файлу')
    result_count = fields.Integer('Кількість записів', readonly=True)
    execution_time = fields.Float('Час виконання (сек)', readonly=True)
    error_message = fields.Text('Повідомлення про помилку')

    @api.model
    def default_get(self, fields_list):
        """Встановлення значень за замовчуванням"""
        res = super().default_get(fields_list)

        if 'report_id' in self.env.context:
            res['report_id'] = self.env.context['report_id']

        if 'export_format' in self.env.context:
            res['export_format'] = self.env.context['export_format']

        return res

    @api.onchange('report_id')
    def _onchange_report_id(self):
        """Налаштування при зміні звіту"""
        if self.report_id:
            self.export_format = self.report_id.export_formats or 'preview'

    def action_execute(self):
        """Виконати звіт"""
        self.ensure_one()

        if not self.report_id:
            raise UserError(_('Не обрано звіт для виконання'))

        self.state = 'executing'

        try:
            start_time = fields.Datetime.now()

            # Підготовка контекстних фільтрів
            context_filters = []
            if self.filter_values:
                try:
                    context_filters = json.loads(self.filter_values)
                    if not isinstance(context_filters, list):
                        context_filters = []
                except json.JSONDecodeError:
                    _logger.warning("Неможливо розпарсити JSON фільтри")
                    context_filters = []

            # Виконання звіту
            data = self.report_id.execute_report(
                context_filters=context_filters,
                limit=self.limit_records if self.limit_records > 0 else None
            )

            # Розрахунок часу виконання
            end_time = fields.Datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            self.write({
                'result_count': len(data) if isinstance(data, list) else 0,
                'execution_time': execution_time,
                'state': 'done'
            })

            if self.export_format == 'preview':
                # Попередній перегляд
                self.result_data = json.dumps(data, default=str, ensure_ascii=False, indent=2)
                return self._return_wizard_form()

            else:
                # Експорт у файл
                return self._export_to_file(data)

        except Exception as e:
            error_msg = str(e)
            _logger.error(f"Помилка виконання звіту {self.report_id.name}: {error_msg}")

            self.write({
                'state': 'error',
                'error_message': error_msg
            })

            return self._return_wizard_form()

    def _export_to_file(self, data):
        """Експорт результатів у файл"""
        try:
            if self.export_format == 'excel':
                file_data = self.report_id.export_to_excel(data)
                filename = f'{self.report_id.name}.xlsx'

            elif self.export_format == 'csv':
                csv_content = self._export_to_csv(data)
                file_data = base64.b64encode(csv_content.encode('utf-8-sig'))
                filename = f'{self.report_id.name}.csv'

            elif self.export_format == 'json':
                json_content = json.dumps(data, default=str, ensure_ascii=False, indent=2)
                file_data = base64.b64encode(json_content.encode('utf-8'))
                filename = f'{self.report_id.name}.json'

            elif self.export_format == 'pdf':
                # TODO: Реалізувати експорт в PDF
                file_data = base64.b64encode(b'PDF export not implemented yet')
                filename = f'{self.report_id.name}.pdf'

            else:
                raise UserError(_('Непідтримуваний формат експорту: %s') % self.export_format)

            self.write({
                'result_file': file_data,
                'result_filename': filename
            })

            return self._return_wizard_form()

        except Exception as e:
            error_msg = f"Помилка експорту: {str(e)}"
            self.write({
                'state': 'error',
                'error_message': error_msg
            })
            return self._return_wizard_form()

    def _export_to_csv(self, data):
        """Експорт в CSV формат"""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        # Заголовки
        visible_fields = self.report_id.field_ids.filtered('visible').sorted('sequence')
        headers = [f.field_label or f.field_name for f in visible_fields]
        writer.writerow(headers)

        # Дані
        if isinstance(data, list) and data and 'group_name' in data[0]:
            # Групировані дані
            for group in data:
                # Заголовок групи
                group_row = [f"ГРУПА: {group['group_name']} ({group['group_count']} записів)"]
                group_row.extend([''] * (len(headers) - 1))
                writer.writerow(group_row)

                # Записи групи
                for record in group['records']:
                    row = []
                    for field in visible_fields:
                        value = record.get(field.field_name, '')
                        if isinstance(value, (list, tuple)) and len(value) > 1:
                            value = value[1]  # Для many2one полів

                        # Форматування значення
                        formatted_value = field.get_formatted_value(value)
                        row.append(formatted_value)
                    writer.writerow(row)

                # Порожній рядок між групами
                writer.writerow([''] * len(headers))
        else:
            # Звичайні дані
            for record in data:
                row = []
                for field in visible_fields:
                    value = record.get(field.field_name, '')
                    if isinstance(value, (list, tuple)) and len(value) > 1:
                        value = value[1]  # Для many2one полів

                    # Форматування значення
                    formatted_value = field.get_formatted_value(value)
                    row.append(formatted_value)
                writer.writerow(row)

        return output.getvalue()

    def _return_wizard_form(self):
        """Повернути форму майстра"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'universal.report.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context
        }

    def action_download_file(self):
        """Завантажити файл"""
        self.ensure_one()

        if not self.result_file:
            raise UserError(_('Немає файлу для завантаження'))

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/universal.report.wizard/{self.id}/result_file/{self.result_filename}?download=true',
            'target': 'self',
        }

    def action_close(self):
        """Закрити майстер"""
        return {'type': 'ir.actions.act_window_close'}

    def action_back_to_report(self):
        """Повернутися до звіту"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'universal.report.builder',
            'res_id': self.report_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def get_preview_data(self):
        """Отримати дані для попереднього перегляду"""
        if not self.result_data:
            return []

        try:
            data = json.loads(self.result_data)
            return data[:100]  # Обмеження для відображення
        except json.JSONDecodeError:
            return []

    @api.model
    def create_quick_report(self, model_name, field_names, filters=None):
        """Створити швидкий звіт програмно"""
        # Знайти модель
        model = self.env['ir.model'].search([('model', '=', model_name)], limit=1)
        if not model:
            raise UserError(_('Модель %s не знайдена') % model_name)

        # Створити тимчасовий звіт
        report = self.env['universal.report.builder'].create({
            'name': _('Швидкий звіт: %s') % model.name,
            'model_id': model.id,
        })

        # Додати поля
        for i, field_name in enumerate(field_names):
            self.env['universal.report.field'].create({
                'report_id': report.id,
                'field_name': field_name,
                'sequence': i + 1,
                'visible': True,
            })

        # Додати фільтри
        if filters:
            for i, filter_data in enumerate(filters):
                self.env['universal.report.filter'].create({
                    'report_id': report.id,
                    'name': filter_data.get('name', f'Фільтр {i + 1}'),
                    'field_name': filter_data['field'],
                    'operator': filter_data.get('operator', '='),
                    'value': str(filter_data['value']),
                    'active': True,
                })

        # Створити майстер
        wizard = self.create({
            'report_id': report.id,
            'export_format': 'preview'
        })

        return wizard


class ReportFilterWizard(models.TransientModel):
    _name = 'report.filter.wizard'
    _description = 'Майстер налаштування фільтрів'

    wizard_id = fields.Many2one('universal.report.wizard', string='Майстер звіту',
                                required=True, ondelete='cascade')
    field_name = fields.Char('Поле', required=True)
    field_label = fields.Char('Заголовок')
    field_type = fields.Char('Тип поля')
    operator = fields.Selection([
        ('=', 'Дорівнює'),
        ('!=', 'Не дорівнює'),
        ('>', 'Більше'),
        ('<', 'Менше'),
        ('>=', 'Більше або дорівнює'),
        ('<=', 'Менше або дорівнює'),
        ('like', 'Містить'),
        ('ilike', 'Містить (без врахування регістру)'),
    ], string='Оператор', default='=')

    value_char = fields.Char('Значення (текст)')
    value_integer = fields.Integer('Значення (число)')
    value_float = fields.Float('Значення (десятковий дріб)')
    value_boolean = fields.Boolean('Значення (логічне)')
    value_date = fields.Date('Значення (дата)')
    value_datetime = fields.Datetime('Значення (дата та час)')
    value_selection = fields.Selection([], string='Значення (вибір)')

    @api.onchange('field_name')
    def _onchange_field_name(self):
        """Налаштування поля при зміні"""
        # Скидання значень за замовчуванням
        self.field_label = self.field_name or ''
        self.field_type = 'char'
        self.value_selection = False

        if not (self.field_name and self.wizard_id.report_id):
            return

        model_name = self.wizard_id.report_id.model_name
        try:
            model_obj = self.env[model_name]
            if not (hasattr(model_obj, '_fields') and self.field_name in model_obj._fields):
                return

            field = model_obj._fields[self.field_name]

            # Встановлення основних властивостей
            self.field_label = field.string or self.field_name
            self.field_type = field.type

            # Обробка selection полів
            if field.type == 'selection' and hasattr(field, 'selection'):
                self._set_selection_value(field, model_obj)

        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning(f"Помилка в _onchange_field_name: {e}")

    def _set_selection_value(self, field, model_obj):
        """Допоміжний метод для встановлення selection значення"""
        try:
            selection_values = field.selection(model_obj) if callable(field.selection) else field.selection

            if (selection_values and
                    isinstance(selection_values, (list, tuple)) and
                    len(selection_values) > 0 and
                    isinstance(selection_values[0], (list, tuple)) and
                    len(selection_values[0]) >= 2):
                self.value_selection = selection_values[0][0]

        except Exception:
            self.value_selection = False

    def get_filter_value(self):
        """Отримати значення фільтра відповідно до типу поля"""
        if self.field_type == 'char' or self.field_type == 'text':
            return self.value_char
        elif self.field_type == 'integer':
            return self.value_integer
        elif self.field_type == 'float' or self.field_type == 'monetary':
            return self.value_float
        elif self.field_type == 'boolean':
            return self.value_boolean
        elif self.field_type == 'date':
            return self.value_date
        elif self.field_type == 'datetime':
            return self.value_datetime
        elif self.field_type == 'selection':
            return self.value_selection
        else:
            return self.value_char