# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReportFieldSelectionWizard(models.TransientModel):
    _name = 'report.field.selection.wizard'
    _description = 'Мастер выбора полей для отчета'

    report_id = fields.Many2one('universal.report.builder', string='Отчет', required=True)
    model_id = fields.Many2one(related='report_id.model_id', readonly=True)

    # Поля для выбора
    field_selection_ids = fields.One2many('report.field.selection.line', 'wizard_id', string='Доступные поля')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        if 'report_id' in self.env.context:
            report_id = self.env.context['report_id']
            report = self.env['universal.report.builder'].browse(report_id)
            res['report_id'] = report_id

            if report.model_id:
                # Получаем доступные поля
                available_fields = report.get_model_fields(report.model_id.model)
                existing_fields = [f.field_name for f in report.field_ids]

                lines = []
                for field_info in available_fields:
                    if field_info['name'] not in existing_fields:
                        lines.append((0, 0, {
                            'field_name': field_info['name'],
                            'field_label': field_info['string'],
                            'field_type': field_info['type'],
                            'selected': False
                        }))

                res['field_selection_ids'] = lines

        return res

    def action_add_selected_fields(self):
        """Добавить выбранные поля к отчету"""
        selected_lines = self.field_selection_ids.filtered('selected')

        if not selected_lines:
            raise UserError(_('Выберите хотя бы одно поле'))

        # Добавляем поля к отчету
        max_sequence = max([f.sequence for f in self.report_id.field_ids] + [0])

        for line in selected_lines:
            self.env['universal.report.field'].create({
                'report_id': self.report_id.id,
                'field_name': line.field_name,
                'field_label': line.field_label,
                'field_type': line.field_type,
                'visible': True,
                'sequence': max_sequence + 1,
                'format_type': self._guess_format_type(line.field_type)
            })
            max_sequence += 1

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'universal.report.builder',
            'res_id': self.report_id.id,
            'view_mode': 'form',
            'target': 'current',
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
            'selection': 'selection'
        }
        return type_map.get(field_type, 'text')


class ReportFieldSelectionLine(models.TransientModel):
    _name = 'report.field.selection.line'
    _description = 'Строка выбора поля'

    wizard_id = fields.Many2one('report.field.selection.wizard', ondelete='cascade')
    field_name = fields.Char('Имя поля', required=True)
    field_label = fields.Char('Заголовок поля', required=True)
    field_type = fields.Char('Тип поля')
    selected = fields.Boolean('Выбрано', default=False)