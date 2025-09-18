# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
import json


class ReportExportWizard(models.TransientModel):
    _name = 'report.export.wizard'
    _description = 'Майстер експорту звітів'

    report_id = fields.Many2one('universal.report.builder', string='Звіт',
                                required=True, readonly=True)

    # Параметри експорту
    export_format = fields.Selection([
        ('excel', 'Microsoft Excel (.xlsx)'),
        ('csv', 'CSV файл (.csv)'),
        ('pdf', 'PDF документ (.pdf)'),
        ('json', 'JSON дані (.json)'),
        ('xml', 'XML дані (.xml)'),
    ], string='Формат експорту', required=True, default='excel')

    # Налаштування Excel
    excel_include_charts = fields.Boolean('Включити діаграми', default=True)
    excel_freeze_header = fields.Boolean('Закріпити заголовки', default=True)
    excel_auto_filter = fields.Boolean('Автофільтр', default=True)
    excel_sheet_name = fields.Char('Назва аркуша', default='Звіт')

    # Налаштування CSV
    csv_delimiter = fields.Selection([
        (';', 'Крапка з комою (;)'),
        (',', 'Кома (,)'),
        ('\t', 'Табуляція'),
        ('|', 'Вертикальна риса (|)'),
    ], string='Роздільник', default=';')
    csv_encoding = fields.Selection([
        ('utf-8', 'UTF-8'),
        ('utf-8-sig', 'UTF-8 з BOM'),
        ('cp1251', 'Windows-1251'),
        ('iso-8859-1', 'ISO-8859-1'),
    ], string='Кодування', default='utf-8-sig')
    csv_include_headers = fields.Boolean('Включити заголовки', default=True)

    # Налаштування PDF
    pdf_orientation = fields.Selection([
        ('portrait', 'Книжкова'),
        ('landscape', 'Альбомна'),
    ], string='Орієнтація', default='portrait')
    pdf_page_size = fields.Selection([
        ('A4', 'A4'),
        ('A3', 'A3'),
        ('Letter', 'Letter'),
        ('Legal', 'Legal'),
    ], string='Розмір сторінки', default='A4')
    pdf_include_logo = fields.Boolean('Включити логотип компанії', default=True)

    # Фільтрування
    include_filters = fields.Boolean('Застосувати фільтри звіту', default=True)
    custom_filters = fields.Text('Додаткові фільтри (JSON)')
    limit_records = fields.Integer('Обмежити кількість записів', default=0,
                                   help='0 = без обмежень')

    # Результат
    result_file = fields.Binary('Файл результату', readonly=True)
    result_filename = fields.Char('Назва файлу', readonly=True)
    export_log = fields.Text('Лог експорту', readonly=True)

    @api.onchange('report_id')
    def _onchange_report_id(self):
        """Автозаповнення при виборі звіту"""
        if self.report_id:
            self.excel_sheet_name = self.report_id.name[:30]  # Excel обмеження

    @api.onchange('export_format')
    def _onchange_export_format(self):
        """Показати відповідні налаштування для формату"""
        # Тут можна додати логіку показу/приховування полів
        pass

    def action_export(self):
        """Виконати експорт"""
        self.ensure_one()

        try:
            # Отримання даних звіту
            context_filters = []
            if self.custom_filters:
                try:
                    context_filters = json.loads(self.custom_filters)
                except json.JSONDecodeError:
                    raise UserError(_('Неправильний формат JSON у додаткових фільтрах'))

            data = self.report_id.execute_report(
                context_filters=context_filters,
                limit=self.limit_records if self.limit_records > 0 else None
            )

            # Експорт у відповідний формат
            if self.export_format == 'excel':
                file_data, filename = self._export_excel(data)
            elif self.export_format == 'csv':
                file_data, filename = self._export_csv(data)
            elif self.export_format == 'pdf':
                file_data, filename = self._export_pdf(data)
            elif self.export_format == 'json':
                file_data, filename = self._export_json(data)
            elif self.export_format == 'xml':
                file_data, filename = self._export_xml(data)
            else:
                raise UserError(_('Непідтримуваний формат експорту'))

            # Збереження результату
            self.write({
                'result_file': file_data,
                'result_filename': filename,
                'export_log': f'Успішно експортовано {len(data)} записів у формат {self.export_format.upper()}'
            })

            return self._return_wizard_view()

        except Exception as e:
            self.export_log = f'Помилка експорту: {str(e)}'
            raise UserError(_('Помилка експорту: %s') % str(e))

    def _export_excel(self, data):
        """Експорт в Excel з розширеними налаштуваннями"""
        import xlsxwriter
        import io

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
            'valign': 'vcenter'
        })

        number_format = workbook.add_format({
            'border': 1,
            'align': 'right',
            'num_format': '#,##0.00'
        })

        # Створення аркуша
        worksheet = workbook.add_worksheet(self.excel_sheet_name)

        # Заголовки
        visible_fields = self.report_id.field_ids.filtered('visible').sorted('sequence')
        headers = [f.field_label or f.field_name for f in visible_fields]

        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
            worksheet.set_column(col, col, max(len(header) + 5, 15))

        # Закріплення заголовків
        if self.excel_freeze_header:
            worksheet.freeze_panes(1, 0)

        # Автофільтр
        if self.excel_auto_filter and data:
            worksheet.autofilter(0, 0, len(data), len(headers) - 1)

        # Дані
        for row_idx, record in enumerate(data, start=1):
            for col_idx, field in enumerate(visible_fields):
                value = record.get(field.field_name, '')
                if isinstance(value, (list, tuple)) and len(value) > 1:
                    value = value[1]

                # Вибір формату ячейки
                cell_fmt = number_format if field.field_type in ('integer', 'float', 'monetary') else cell_format
                worksheet.write(row_idx, col_idx, value or '', cell_fmt)

        workbook.close()
        output.seek(0)

        filename = f"{self.report_id.name}.xlsx"
        return base64.b64encode(output.read()), filename

    def _export_csv(self, data):
        """Експорт в CSV з налаштуваннями"""
        import csv
        import io

        output = io.StringIO()

        # Налаштування CSV writer
        delimiter = self.csv_delimiter
        if delimiter == '\t':
            delimiter = '\t'

        writer = csv.writer(output, delimiter=delimiter,
                            quotechar='"', quoting=csv.QUOTE_MINIMAL)

        visible_fields = self.report_id.field_ids.filtered('visible').sorted('sequence')

        # Заголовки
        if self.csv_include_headers:
            headers = [f.field_label or f.field_name for f in visible_fields]
            writer.writerow(headers)

        # Дані
        for record in data:
            row = []
            for field in visible_fields:
                value = record.get(field.field_name, '')
                if isinstance(value, (list, tuple)) and len(value) > 1:
                    value = value[1]

                # Форматування значення
                formatted_value = field.get_formatted_value(value) if hasattr(field, 'get_formatted_value') else str(
                    value)
                row.append(formatted_value)
            writer.writerow(row)

        # Кодування
        content = output.getvalue()
        encoded_content = content.encode(self.csv_encoding)

        filename = f"{self.report_id.name}.csv"
        return base64.b64encode(encoded_content), filename

    def _export_json(self, data):
        """Експорт в JSON"""
        visible_fields = self.report_id.field_ids.filtered('visible').sorted('sequence')

        # Підготовка структури даних
        export_data = {
            'report_info': {
                'name': self.report_id.name,
                'model': self.report_id.model_name,
                'generated_at': fields.Datetime.now().isoformat(),
                'total_records': len(data)
            },
            'fields': [
                {
                    'name': f.field_name,
                    'label': f.field_label or f.field_name,
                    'type': f.field_type,
                    'format': f.format_type
                } for f in visible_fields
            ],
            'data': []
        }

        # Підготовка даних
        for record in data:
            row_data = {}
            for field in visible_fields:
                value = record.get(field.field_name, '')
                if isinstance(value, (list, tuple)) and len(value) > 1:
                    value = value[1]
                row_data[field.field_name] = value
            export_data['data'].append(row_data)

        json_content = json.dumps(export_data, default=str, ensure_ascii=False, indent=2)
        filename = f"{self.report_id.name}.json"

        return base64.b64encode(json_content.encode('utf-8')), filename

    def _export_xml(self, data):
        """Експорт в XML"""
        from xml.etree.ElementTree import Element, SubElement, tostring
        from xml.dom import minidom

        # Створення кореневого елемента
        root = Element('report')
        root.set('name', self.report_id.name)
        root.set('model', self.report_id.model_name)
        root.set('generated_at', fields.Datetime.now().isoformat())

        # Інформація про поля
        fields_elem = SubElement(root, 'fields')
        visible_fields = self.report_id.field_ids.filtered('visible').sorted('sequence')

        for field in visible_fields:
            field_elem = SubElement(fields_elem, 'field')
            field_elem.set('name', field.field_name)
            field_elem.set('label', field.field_label or field.field_name)
            field_elem.set('type', field.field_type or 'char')

        # Дані
        data_elem = SubElement(root, 'data')
        for record in data:
            record_elem = SubElement(data_elem, 'record')
            for field in visible_fields:
                value = record.get(field.field_name, '')
                if isinstance(value, (list, tuple)) and len(value) > 1:
                    value = value[1]

                field_elem = SubElement(record_elem, field.field_name)
                field_elem.text = str(value) if value is not None else ''

        # Форматування XML
        rough_string = tostring(root, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="  ", encoding='utf-8')

        filename = f"{self.report_id.name}.xml"
        return base64.b64encode(pretty_xml), filename

    def _export_pdf(self, data):
        """Експорт в PDF (базова реалізація)"""
        # TODO: Реалізувати повноцінний експорт в PDF
        # Поки що заглушка
        content = f"PDF експорт звіту '{self.report_id.name}'\n"
        content += f"Кількість записів: {len(data)}\n"
        content += "Функція в розробці..."

        filename = f"{self.report_id.name}.pdf"
        return base64.b64encode(content.encode('utf-8')), filename

    def _return_wizard_view(self):
        """Повернути представлення майстра"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'report.export.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context
        }

    def action_download(self):
        """Завантажити файл"""
        if not self.result_file:
            raise UserError(_('Спочатку виконайте експорт'))

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/report.export.wizard/{self.id}/result_file/{self.result_filename}?download=true',
            'target': 'self',
        }

    def action_reset(self):
        """Скинути результат для нового експорту"""
        self.write({
            'result_file': False,
            'result_filename': False,
            'export_log': False
        })

        return self._return_wizard_view()