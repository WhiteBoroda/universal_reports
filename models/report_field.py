# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class UniversalReportField(models.Model):
    _name = 'universal.report.field'
    _description = 'Поле звіту'
    _order = 'sequence, id'

    report_id = fields.Many2one('universal.report.builder', string='Звіт',
                                ondelete='cascade', required=True)
    sequence = fields.Integer('Послідовність', default=10)
    field_name = fields.Char('Назва поля', required=True)
    field_label = fields.Char('Заголовок поля', translate=True)
    field_type = fields.Char('Тип поля')
    visible = fields.Boolean('Відображати', default=True)
    width = fields.Integer('Ширина колонки', default=100)

    # Агрегація
    aggregation = fields.Selection([
        ('none', 'Без агрегації'),
        ('sum', 'Сума'),
        ('avg', 'Середнє'),
        ('count', 'Кількість'),
        ('min', 'Мінімум'),
        ('max', 'Максимум'),
    ], string='Агрегація', default='none')

    # Форматування
    format_type = fields.Selection([
        ('text', 'Текст'),
        ('number', 'Число'),
        ('currency', 'Валюта'),
        ('date', 'Дата'),
        ('datetime', 'Дата та час'),
        ('boolean', 'Логічний'),
        ('selection', 'Вибір'),
    ], string='Формат', default='text')

    decimal_places = fields.Integer('Знаків після коми', default=2)
    thousands_separator = fields.Boolean('Розділювач тисяч', default=False)

    @api.constrains('field_name', 'report_id')
    def _check_unique_field(self):
        """Перевірка унікальності поля в звіті"""
        for record in self:
            if record.report_id:
                existing = self.search([
                    ('report_id', '=', record.report_id.id),
                    ('field_name', '=', record.field_name),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_('Поле "%s" вже додано до звіту') % record.field_name)

    @api.onchange('field_name')
    def _onchange_field_name(self):
        """Автозаповнення заголовка поля"""
        if self.field_name and self.report_id and self.report_id.model_name:
            try:
                model_obj = self.env[self.report_id.model_name]
                if hasattr(model_obj, '_fields') and self.field_name in model_obj._fields:
                    field = model_obj._fields[self.field_name]
                    if not self.field_label:
                        self.field_label = field.string or self.field_name
                    self.field_type = field.type

                    # Автовизначення формату
                    if field.type in ('integer', 'float', 'monetary'):
                        self.format_type = 'currency' if field.type == 'monetary' else 'number'
                    elif field.type in ('date', 'datetime'):
                        self.format_type = field.type
                    elif field.type == 'boolean':
                        self.format_type = 'boolean'
                    elif field.type == 'selection':
                        self.format_type = 'selection'
                    else:
                        self.format_type = 'text'
            except:
                pass

    def get_formatted_value(self, value):
        """Отримати відформатоване значення"""
        if value is None or value == '':
            return ''

        if self.format_type == 'boolean':
            return _('Так') if value else _('Ні')
        elif self.format_type == 'number':
            try:
                num_value = float(value)
                if self.thousands_separator:
                    return f"{num_value:,.{self.decimal_places}f}"
                else:
                    return f"{num_value:.{self.decimal_places}f}"
            except (ValueError, TypeError):
                return str(value)
        elif self.format_type == 'currency':
            try:
                num_value = float(value)
                currency_symbol = self.env.user.company_id.currency_id.symbol or '₴'
                if self.thousands_separator:
                    return f"{num_value:,.{self.decimal_places}f} {currency_symbol}"
                else:
                    return f"{num_value:.{self.decimal_places}f} {currency_symbol}"
            except (ValueError, TypeError):
                return str(value)
        elif self.format_type == 'date':
            try:
                if hasattr(value, 'strftime'):
                    return value.strftime('%d.%m.%Y')
                elif isinstance(value, str):
                    from datetime import datetime
                    date_obj = datetime.strptime(value[:10], '%Y-%m-%d')
                    return date_obj.strftime('%d.%m.%Y')
            except:
                pass
            return str(value)
        elif self.format_type == 'datetime':
            try:
                if hasattr(value, 'strftime'):
                    return value.strftime('%d.%m.%Y %H:%M')
                elif isinstance(value, str):
                    from datetime import datetime
                    datetime_obj = datetime.strptime(value[:19], '%Y-%m-%d %H:%M:%S')
                    return datetime_obj.strftime('%d.%m.%Y %H:%M')
            except:
                pass
            return str(value)
        else:
            return str(value)


class UniversalReportFilter(models.Model):
    _name = 'universal.report.filter'
    _description = 'Фільтр звіту'
    _order = 'sequence, id'

    report_id = fields.Many2one('universal.report.builder', string='Звіт',
                                ondelete='cascade', required=True)
    sequence = fields.Integer('Послідовність', default=10)
    name = fields.Char('Назва фільтра', required=True, translate=True)
    field_name = fields.Char('Поле', required=True)
    field_type = fields.Char('Тип поля')

    operator = fields.Selection([
        ('=', 'Дорівнює'),
        ('!=', 'Не дорівнює'),
        ('>', 'Більше'),
        ('>=', 'Більше або дорівнює'),
        ('<', 'Менше'),
        ('<=', 'Менше або дорівнює'),
        ('like', 'Містить'),
        ('ilike', 'Містить (без врахування регістру)'),
        ('in', 'У списку'),
        ('not in', 'Не у списку'),
        ('=?', 'Не встановлено'),
        ('!=', 'Встановлено'),
    ], string='Оператор', default='=', required=True)

    value = fields.Char('Значення')
    value_type = fields.Selection([
        ('static', 'Статичне значення'),
        ('user_input', 'Введення користувача'),
        ('context', 'З контексту'),
        ('current_user', 'Поточний користувач'),
        ('current_date', 'Поточна дата'),
    ], string='Тип значення', default='static')

    active = fields.Boolean('Активний', default=True)
    required = fields.Boolean('Обов\'язковий', default=False)

    @api.onchange('field_name')
    def _onchange_field_name(self):
        """Автозаповнення типу поля"""
        if self.field_name and self.report_id and self.report_id.model_name:
            try:
                model_obj = self.env[self.report_id.model_name]
                if hasattr(model_obj, '_fields') and self.field_name in model_obj._fields:
                    field = model_obj._fields[self.field_name]
                    self.field_type = field.type
                    if not self.name:
                        self.name = _('Фільтр: %s') % (field.string or self.field_name)
            except:
                pass


class UniversalReportGroup(models.Model):
    _name = 'universal.report.group'
    _description = 'Групування звіту'
    _order = 'sequence, id'

    report_id = fields.Many2one('universal.report.builder', string='Звіт',
                                ondelete='cascade', required=True)
    sequence = fields.Integer('Послідовність', default=10)
    field_name = fields.Char('Поле групування', required=True)
    field_label = fields.Char('Заголовок групи', translate=True)
    show_totals = fields.Boolean('Показувати підсумки', default=True)

    @api.onchange('field_name')
    def _onchange_field_name(self):
        """Автозаповнення заголовка групи"""
        if self.field_name and self.report_id and self.report_id.model_name:
            try:
                model_obj = self.env[self.report_id.model_name]
                if hasattr(model_obj, '_fields') and self.field_name in model_obj._fields:
                    field = model_obj._fields[self.field_name]
                    if not self.field_label:
                        self.field_label = field.string or self.field_name
            except:
                pass


class UniversalReportSort(models.Model):
    _name = 'universal.report.sort'
    _description = 'Сортування звіту'
    _order = 'sequence, id'

    report_id = fields.Many2one('universal.report.builder', string='Звіт',
                                ondelete='cascade', required=True)
    sequence = fields.Integer('Послідовність', default=10)
    field_name = fields.Char('Поле сортування', required=True)
    direction = fields.Selection([
        ('asc', 'За зростанням'),
        ('desc', 'За спаданням'),
    ], string='Напрямок', default='asc', required=True)