# wizard/field_selection_wizard.py - УЛУЧШЕННАЯ ВЕРСИЯ

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReportFieldSelectionWizard(models.TransientModel):
    _name = 'report.field.selection.wizard'
    _description = 'Мастер выбора полей для отчета'

    report_id = fields.Many2one('universal.report.builder', string='Отчет',
                                required=True, readonly=True)
    model_id = fields.Many2one(related='report_id.model_id', readonly=True)

    # Поля для выбора
    field_selection_ids = fields.One2many('report.field.selection.line', 'wizard_id',
                                          string='Доступные поля')

    # Счетчики
    total_fields_count = fields.Integer('Всего полей', compute='_compute_field_counts')
    selected_fields_count = fields.Integer('Выбрано полей', compute='_compute_field_counts')

    @api.depends('field_selection_ids.selected')
    def _compute_field_counts(self):
        """Вычисление счетчиков полей"""
        for wizard in self:
            wizard.total_fields_count = len(wizard.field_selection_ids)
            wizard.selected_fields_count = len(wizard.field_selection_ids.filtered('selected'))

    @api.model
    def default_get(self, fields_list):
        """Загрузка полей по умолчанию с улучшенной обработкой"""
        res = super().default_get(fields_list)

        report_id = self.env.context.get('default_report_id') or self.env.context.get('active_id')
        if report_id:
            report = self.env['universal.report.builder'].browse(report_id)
            res['report_id'] = report_id

            if report.model_id:
                try:
                    # Получаем поля модели
                    available_fields = report.get_model_fields(report.model_id.model)
                    existing_fields = [f.field_name for f in report.field_ids]

                    lines = []
                    for seq, field_info in enumerate(available_fields, 1):
                        if field_info['name'] not in existing_fields:
                            # Улучшенная обработка типов полей
                            field_type_display = self._get_field_type_display(field_info['type'])

                            lines.append((0, 0, {
                                'sequence': seq,
                                'field_name': field_info['name'],
                                'field_label': field_info['string'] or field_info['name'],
                                'field_type': field_info['type'],
                                'field_type_display': field_type_display,
                                'selected': False,
                                'is_required': field_info.get('required', False),
                                'help_text': field_info.get('help', '') or
                                             self._get_field_description(field_info['type']),
                            }))

                    res['field_selection_ids'] = lines

                except Exception as e:
                    import logging
                    _logger = logging.getLogger(__name__)
                    _logger.warning(f"Ошибка загрузки полей для модели {report.model_id.model}: {e}")

        return res

    @api.model
    def _get_field_type_display(self, field_type):
        """Получить читаемое название типа поля"""
        type_mapping = {
            'char': 'Текст',
            'text': 'Многострочный текст',
            'integer': 'Целое число',
            'float': 'Дробное число',
            'monetary': 'Денежная сумма',
            'boolean': 'Да/Нет',
            'date': 'Дата',
            'datetime': 'Дата и время',
            'selection': 'Выбор из списка',
            'many2one': 'Связь (один)',
            'one2many': 'Связь (много)',
            'many2many': 'Связь (многие ко многим)',
            'binary': 'Файл',
            'html': 'HTML текст',
            'reference': 'Ссылка',
        }
        return type_mapping.get(field_type, field_type.title())

    @api.model
    def _get_field_description(self, field_type):
        """Получить описание поля по типу"""
        descriptions = {
            'char': 'Короткая текстовая строка',
            'text': 'Длинный текст, многострочный',
            'integer': 'Целое число без дробной части',
            'float': 'Число с дробной частью',
            'monetary': 'Денежная сумма с валютой',
            'boolean': 'Логическое поле Да/Нет',
            'date': 'Дата без времени',
            'datetime': 'Дата с временем',
            'selection': 'Выбор из предустановленных вариантов',
            'many2one': 'Ссылка на другую запись',
            'one2many': 'Список связанных записей',
            'many2many': 'Множественные связи',
            'binary': 'Файл или изображение',
            'html': 'Форматированный HTML текст',
        }
        return descriptions.get(field_type, 'Специальный тип поля')

    def action_add_selected_fields(self):
        """Добавить выбранные поля к отчету"""
        selected_lines = self.field_selection_ids.filtered('selected')

        if not selected_lines:
            raise UserError(_('Выберите хотя бы одно поле для добавления'))

        # Добавляем поля к отчету
        max_sequence = max([f.sequence for f in self.report_id.field_ids] + [0])

        created_fields = []
        for line in selected_lines:
            field_data = {
                'report_id': self.report_id.id,
                'field_name': line.field_name,
                'field_label': line.field_label,
                'field_type': line.field_type,
                'visible': True,
                'sequence': max_sequence + 1,
                'format_type': self._guess_format_type(line.field_type)
            }

            field = self.env['universal.report.field'].create(field_data)
            created_fields.append(field)
            max_sequence += 1

        # Возвращаемся к форме отчета
        return {
            'type': 'ir.actions.act_window',
            'name': _('Отчет'),
            'res_model': 'universal.report.builder',
            'res_id': self.report_id.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'message': f'Успешно добавлено полей: {len(created_fields)}'
            }
        }

    def action_select_all(self):
        """Выбрать все поля"""
        count = len(self.field_selection_ids)
        self.field_selection_ids.write({'selected': True})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Успешно'),
                'message': _('Выбрано полей: %d') % count,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_deselect_all(self):
        """Снять выбор со всех полей"""
        self.field_selection_ids.write({'selected': False})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Выполнено'),
                'message': _('Выбор снят со всех полей'),
                'type': 'info',
                'sticky': False,
            }
        }

    def action_select_basic_fields(self):
        """Выбрать основные поля"""
        basic_fields = [
            'name', 'email', 'phone', 'mobile', 'active',
            'create_date', 'write_date', 'display_name',
            'company_id', 'user_id', 'partner_id'
        ]

        # Сначала снимаем все
        self.field_selection_ids.write({'selected': False})

        # Выбираем основные
        selected_count = 0
        for line in self.field_selection_ids:
            if line.field_name in basic_fields:
                line.selected = True
                selected_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Основные поля'),
                'message': _('Выбрано основных полей: %d') % selected_count,
                'type': 'success',
                'sticky': False,
            }
        }

    def _guess_format_type(self, field_type):
        """Автоматическое определение типа форматирования"""
        type_map = {
            'char': 'text',
            'text': 'text',
            'integer': 'number',
            'float': 'number',
            'monetary': 'currency',
            'date': 'date',
            'datetime': 'datetime',
            'boolean': 'boolean',
            'selection': 'selection',
            'many2one': 'text',
            'one2many': 'text',
            'many2many': 'text',
            'html': 'text',
        }
        return type_map.get(field_type, 'text')

class ReportFieldSelectionLine(models.TransientModel):
    _name = 'report.field.selection.line'
    _description = 'Строка выбора поля'
    _order = 'sequence, field_label'

    wizard_id = fields.Many2one('report.field.selection.wizard',
                                ondelete='cascade', required=True)
    sequence = fields.Integer('Последовательность', default=10)
    field_name = fields.Char('Имя поля', required=True)
    field_label = fields.Char('Заголовок поля', required=True)
    field_type = fields.Char('Тип поля')
    field_type_display = fields.Char('Тип поля (отображение)')
    selected = fields.Boolean('Выбрано', default=False)
    is_required = fields.Boolean('Обязательное', readonly=True)
    help_text = fields.Text('Описание', readonly=True)