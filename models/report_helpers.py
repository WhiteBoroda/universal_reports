# -*- coding: utf-8 -*-

import xlsxwriter
import csv
import base64
from io import BytesIO, StringIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
import json
from datetime import datetime, date


class ReportExporter:
    """Клас для експорту звітів у різні формати"""

    def __init__(self, report_builder, data):
        self.report = report_builder
        self.data = data
        self.visible_fields = report_builder.field_ids.filtered('visible')

    def to_excel(self):
        """Експорт в Excel з розширеними можливостями"""
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Створюємо стилі
        styles = self._create_excel_styles(workbook)

        # Основний лист з даними
        worksheet = workbook.add_worksheet('Дані')
        self._write_excel_data(worksheet, styles)

        # Лист з метаданими
        meta_worksheet = workbook.add_worksheet('Інформація')
        self._write_excel_metadata(meta_worksheet, styles)

        # Діаграма якщо є числові поля
        if self._has_numeric_fields():
            chart_worksheet = workbook.add_worksheet('Діаграма')
            self._create_excel_chart(workbook, chart_worksheet)

        workbook.close()
        output.seek(0)
        return output.getvalue()

    def to_pdf(self):
        """Експорт в PDF з професійним оформленням"""
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4)

        # Підготовуємо дані для таблиці
        table_data = self._prepare_pdf_data()

        # Створюємо таблицю
        table = Table(table_data)
        table.setStyle(self._get_pdf_table_style())

        # Будуємо документ
        story = [table]
        doc.build(story)

        output.seek(0)
        return output.getvalue()

    def to_csv(self, delimiter=';', encoding='utf-8'):
        """Експорт в CSV з налаштовуваними параметрами"""
        output = StringIO()
        writer = csv.writer(output, delimiter=delimiter)

        # Заголовки
        headers = [f.field_label or f.field_name for f in self.visible_fields]
        writer.writerow(headers)

        # Дані
        for record in self.data:
            row = []
            for field in self.visible_fields:
                value = record.get(field.field_name, '')
                # Форматуємо значення
                formatted_value = self._format_csv_value(value, field)
                row.append(formatted_value)
            writer.writerow(row)

        content = output.getvalue()
        return content.encode(encoding)

    def to_json(self):
        """Експорт в JSON"""
        result = {
            'report_name': self.report.name,
            'generated_at': datetime.now().isoformat(),
            'model': self.report.model_name,
            'fields': [
                {
                    'name': f.field_name,
                    'label': f.field_label,
                    'type': f.field_type
                } for f in self.visible_fields
            ],
            'data': self.data,
            'summary': {
                'total_records': len(self.data),
                'fields_count': len(self.visible_fields)
            }
        }
        return json.dumps(result, default=str, ensure_ascii=False, indent=2)

    def _create_excel_styles(self, workbook):
        """Створення стилів для Excel"""
        return {
            'header': workbook.add_format({
                'bold': True,
                'bg_color': '#366092',
                'font_color': 'white',
                'border': 1,
                'align': 'center',
                'valign': 'vcenter',
                'text_wrap': True
            }),
            'cell': workbook.add_format({
                'border': 1,
                'valign': 'vcenter'
            }),
            'number': workbook.add_format({
                'border': 1,
                'num_format': '#,##0.00',
                'align': 'right'
            }),
            'date': workbook.add_format({
                'border': 1,
                'num_format': 'dd/mm/yyyy'
            }),
            'title': workbook.add_format({
                'bold': True,
                'font_size': 16,
                'font_color': '#366092'
            })
        }

    def _write_excel_data(self, worksheet, styles):
        """Запис даних в Excel лист"""
        # Заголовок звіту
        if self.visible_fields:
            worksheet.merge_range('A1:{}1'.format(chr(65 + len(self.visible_fields) - 1)),
                                  self.report.name, styles['title'])

        # Заголовки колонок
        for col, field in enumerate(self.visible_fields):
            worksheet.write(2, col, field.field_label or field.field_name, styles['header'])
            # Встановлюємо ширину колонки
            worksheet.set_column(col, col, max(len(str(field.field_label or field.field_name)) + 2, 10))

        # Дані
        for row, record in enumerate(self.data, start=3):
            for col, field in enumerate(self.visible_fields):
                value = record.get(field.field_name, '')
                style = self._get_excel_cell_style(field, styles)
                worksheet.write(row, col, self._format_excel_value(value, field), style)

    def _write_excel_metadata(self, worksheet, styles):
        """Запис метаданих в Excel"""
        metadata = [
            ['Назва звіту', self.report.name],
            ['Модель даних', self.report.model_id.name],
            ['Дата створення', datetime.now().strftime('%d.%m.%Y %H:%M')],
            ['Кількість записів', len(self.data)],
            ['Кількість полів', len(self.visible_fields)]
        ]

        for row, (key, value) in enumerate(metadata):
            worksheet.write(row, 0, key, styles['header'])
            worksheet.write(row, 1, value, styles['cell'])

        worksheet.set_column(0, 0, 20)
        worksheet.set_column(1, 1, 30)

    def _has_numeric_fields(self):
        """Перевірка наявності числових полів для діаграми"""
        return any(f.field_type in ('integer', 'float', 'monetary')
                   for f in self.visible_fields)

    def _create_excel_chart(self, workbook, worksheet):
        """Створення діаграми в Excel"""
        if not self._has_numeric_fields() or not self.data:
            return

        # Простий приклад діаграми
        chart = workbook.add_chart({'type': 'column'})

        # Знайдемо перше числове поле
        numeric_field = None
        numeric_col = 0
        for col, field in enumerate(self.visible_fields):
            if field.field_type in ('integer', 'float', 'monetary'):
                numeric_field = field
                numeric_col = col
                break

        if numeric_field and len(self.data) > 1:
            # Додаємо серію даних (перші 10 записів максимум)
            data_rows = min(len(self.data), 10)
            chart.add_series({
                'categories': ['Дані', 3, 0, 3 + data_rows - 1, 0],  # Перша колонка як категорії
                'values': ['Дані', 3, numeric_col, 3 + data_rows - 1, numeric_col],  # Числові значення
                'name': numeric_field.field_label or numeric_field.field_name,
            })

            chart.set_title({'name': f'Діаграма: {numeric_field.field_label or numeric_field.field_name}'})
            worksheet.insert_chart('B2', chart)

    def _format_excel_value(self, value, field):
        """Форматування значення для Excel"""
        if value is None or value == '':
            return ''

        if field.field_type in ('integer', 'float', 'monetary'):
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0
        elif field.field_type == 'boolean':
            return 'Так' if value else 'Ні'
        elif field.field_type in ('date', 'datetime'):
            if isinstance(value, str):
                try:
                    return datetime.strptime(value[:19], '%Y-%m-%d %H:%M:%S').date()
                except ValueError:
                    return value
            return value

        return str(value)

    def _get_excel_cell_style(self, field, styles):
        """Отримання стилю комірки для Excel"""
        if field.field_type in ('integer', 'float', 'monetary'):
            return styles['number']
        elif field.field_type in ('date', 'datetime'):
            return styles['date']
        else:
            return styles['cell']

    def _format_csv_value(self, value, field):
        """Форматування значення для CSV"""
        if value is None or value == '':
            return ''

        if field.field_type == 'boolean':
            return 'Так' if value else 'Ні'
        elif field.field_type in ('date', 'datetime'):
            if hasattr(value, 'strftime'):
                return value.strftime('%d.%m.%Y %H:%M:%S' if field.field_type == 'datetime' else '%d.%m.%Y')

        return str(value).replace('\n', ' ').replace('\r', ' ')

    def _prepare_pdf_data(self):
        """Підготовка даних для PDF таблиці"""
        # Заголовки
        headers = [f.field_label or f.field_name for f in self.visible_fields]
        table_data = [headers]

        # Дані (обмежуємо кількість для PDF)
        max_rows = min(len(self.data), 50)  # PDF не любить великі таблиці
        for i in range(max_rows):
            record = self.data[i]
            row = []
            for field in self.visible_fields:
                value = record.get(field.field_name, '')
                formatted_value = self._format_csv_value(value, field)
                # Обрізаємо довгі рядки для PDF
                if len(str(formatted_value)) > 50:
                    formatted_value = str(formatted_value)[:47] + '...'
                row.append(str(formatted_value))
            table_data.append(row)

        return table_data

    def _get_pdf_table_style(self):
        """Стиль для PDF таблиці"""
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ])