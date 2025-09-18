# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import json
import base64
import logging

_logger = logging.getLogger(__name__)


class ReportImportWizard(models.TransientModel):
    _name = 'report.import.wizard'
    _description = 'Майстер імпорту налаштувань звіту'

    settings_file = fields.Binary('Файл налаштувань', required=True)
    settings_filename = fields.Char('Назва файлу')
    overwrite_existing = fields.Boolean('Перезаписати існуючий звіт', default=False)

    # Результат імпорту
    state = fields.Selection([
        ('draft', 'Підготовка'),
        ('importing', 'Імпорт'),
        ('done', 'Завершено'),
        ('error', 'Помилка'),
    ], string='Статус', default='draft')

    import_log = fields.Text('Лог імпорту', readonly=True)
    created_report_id = fields.Many2one('universal.report.builder',
                                        string='Створений звіт', readonly=True)

    def action_import(self):
        """Виконати імпорт налаштувань"""
        self.ensure_one()

        if not self.settings_file:
            raise UserError(_('Оберіть файл з налаштуваннями'))

        self.state = 'importing'

        try:
            # Декодуємо файл
            file_content = base64.b64decode(self.settings_file).decode('utf-8')
            settings_data = json.loads(file_content)

            # Валідуємо структуру
            self._validate_settings_structure(settings_data)

            # Створюємо звіт
            report = self._create_report_from_settings(settings_data)

            log_message = f"Звіт '{report.name}' успішно створено з імпортованих налаштувань.\n"
            log_message += f"ID звіту: {report.id}\n"
            log_message += f"Полів імпортовано: {len(report.field_ids)}\n"
            log_message += f"Фільтрів імпортовано: {len(report.filter_ids)}\n"

            self.write({
                'state': 'done',
                'import_log': log_message,
                'created_report_id': report.id
            })

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'report.import.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
                'context': self.env.context
            }

        except json.JSONDecodeError as e:
            error_msg = f"Помилка розбору JSON: {str(e)}"
            _logger.error(error_msg)
            self._handle_import_error(error_msg)

        except ValidationError as e:
            error_msg = f"Помилка валідації: {str(e)}"
            _logger.error(error_msg)
            self._handle_import_error(error_msg)

        except Exception as e:
            error_msg = f"Неочікувана помилка: {str(e)}"
            _logger.error(error_msg)
            self._handle_import_error(error_msg)

    def _validate_settings_structure(self, settings_data):
        """Валідація структури налаштувань"""
        required_keys = ['name', 'model', 'fields']

        for key in required_keys:
            if key not in settings_data:
                raise ValidationError(_('Відсутнє обов\'язкове поле: %s') % key)

        # Перевіряємо чи існує модель
        model = self.env['ir.model'].search([('model', '=', settings_data['model'])], limit=1)
        if not model:
            raise ValidationError(_('Модель не знайдена: %s') % settings_data['model'])

        # Перевіряємо поля
        if not isinstance(settings_data['fields'], list) or not settings_data['fields']:
            raise ValidationError(_('Повинно бути вказано хоча б одне поле'))

        # Перевіряємо чи існують поля в моделі
        model_obj = self.env[settings_data['model']]
        for field_data in settings_data['fields']:
            field_name = field_data.get('name')
            if not field_name:
                raise ValidationError(_('Поле повинно мати назву'))

            if field_name not in model_obj._fields:
                raise ValidationError(_('Поле не існує в моделі: %s') % field_name)

    def _create_report_from_settings(self, settings_data):
        """Створення звіту з налаштувань"""
        # Пошук існуючого звіту
        existing_report = None
        if self.overwrite_existing:
            existing_report = self.env['universal.report.builder'].search([
                ('name', '=', settings_data['name'])
            ], limit=1)

        if existing_report and not self.overwrite_existing:
            raise UserError(_('Звіт з такою назвою вже існує. Увімкніть опцію перезапису або змініть назву.'))

        # Знаходимо модель
        model = self.env['ir.model'].search([('model', '=', settings_data['model'])], limit=1)

        # Дані для створення звіту
        report_data = {
            'name': settings_data['name'],
            'description': settings_data.get('description', ''),
            'model_id': model.id,
            'format_type': settings_data.get('format_type', 'table'),
            'is_template': settings_data.get('is_template', False),
            'export_formats': settings_data.get('export_formats', 'excel'),
        }

        if existing_report:
            # Видаляємо старі дочірні записи
            existing_report.field_ids.unlink()
            existing_report.filter_ids.unlink()
            existing_report.group_ids.unlink()
            existing_report.sort_ids.unlink()

            existing_report.write(report_data)
            report = existing_report
        else:
            report = self.env['universal.report.builder'].create(report_data)

        # Створення полів
        for seq, field_data in enumerate(settings_data['fields'], 1):
            field_values = {
                'report_id': report.id,
                'sequence': seq,
                'field_name': field_data['name'],
                'field_label': field_data.get('label', field_data['name']),
                'field_type': field_data.get('type', 'char'),
                'visible': field_data.get('visible', True),
                'format_type': field_data.get('format', 'text'),
                'aggregation': field_data.get('aggregation', 'none'),
                'width': field_data.get('width', 100),
                'decimal_places': field_data.get('decimal_places', 2),
            }
            self.env['universal.report.field'].create(field_values)

        # Створення фільтрів
        if 'filters' in settings_data:
            for seq, filter_data in enumerate(settings_data['filters'], 1):
                filter_values = {
                    'report_id': report.id,
                    'sequence': seq,
                    'name': filter_data.get('name', f'Фільтр {seq}'),
                    'field_name': filter_data['field'],
                    'operator': filter_data.get('operator', '='),
                    'value': str(filter_data.get('value', '')),
                    'value_type': filter_data.get('value_type', 'static'),
                    'active': filter_data.get('active', True),
                    'required': filter_data.get('required', False),
                }
                self.env['universal.report.filter'].create(filter_values)

        # Створення групувань
        if 'groups' in settings_data:
            for seq, group_data in enumerate(settings_data['groups'], 1):
                group_values = {
                    'report_id': report.id,
                    'sequence': seq,
                    'field_name': group_data['field'],
                    'field_label': group_data.get('label', ''),
                    'show_totals': group_data.get('show_totals', True),
                }
                self.env['universal.report.group'].create(group_values)

        # Створення сортувань
        if 'sorts' in settings_data:
            for seq, sort_data in enumerate(settings_data['sorts'], 1):
                sort_values = {
                    'report_id': report.id,
                    'sequence': seq,
                    'field_name': sort_data['field'],
                    'direction': sort_data.get('direction', 'asc'),
                }
                self.env['universal.report.sort'].create(sort_values)

        return report

    def _handle_import_error(self, error_msg):
        """Обробка помилки імпорту"""
        self.write({
            'state': 'error',
            'import_log': error_msg
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'report.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context
        }

    def action_open_report(self):
        """Відкрити створений звіт"""
        if not self.created_report_id:
            raise UserError(_('Звіт не створено'))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'universal.report.builder',
            'res_id': self.created_report_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_close(self):
        """Закрити майстер"""
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def create_sample_settings_file(self):
        """Створити зразок файлу налаштувань"""
        sample_settings = {
            "name": "Приклад звіту по партнерах",
            "description": "Демонстраційний звіт створений з імпорту",
            "model": "res.partner",
            "format_type": "table",
            "export_formats": "excel",
            "is_template": False,
            "fields": [
                {
                    "name": "name",
                    "label": "Назва партнера",
                    "type": "char",
                    "visible": True,
                    "format": "text",
                    "aggregation": "none",
                    "width": 200
                },
                {
                    "name": "email",
                    "label": "Електронна пошта",
                    "type": "char",
                    "visible": True,
                    "format": "text",
                    "width": 150
                },
                {
                    "name": "phone",
                    "label": "Телефон",
                    "type": "char",
                    "visible": True,
                    "format": "text",
                    "width": 120
                },
                {
                    "name": "is_company",
                    "label": "Це компанія",
                    "type": "boolean",
                    "visible": True,
                    "format": "boolean",
                    "width": 100
                }
            ],
            "filters": [
                {
                    "name": "Тільки активні",
                    "field": "active",
                    "operator": "=",
                    "value": "True",
                    "active": True,
                    "required": False
                }
            ],
            "groups": [],
            "sorts": [
                {
                    "field": "name",
                    "direction": "asc"
                }
            ]
        }

        return json.dumps(sample_settings, ensure_ascii=False, indent=2)