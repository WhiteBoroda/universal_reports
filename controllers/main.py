# -*- coding: utf-8 -*-

from odoo import http, fields
from odoo.http import request, Response
from odoo.exceptions import AccessDenied, UserError
import json
import base64
import logging

_logger = logging.getLogger(__name__)


class UniversalReportsController(http.Controller):
    """HTTP контролер для універсальних звітів"""

    @http.route('/universal_reports/get_model_fields', type='json', auth='user')
    def get_model_fields(self, model_name):
        """API для отримання полів моделі"""
        try:
            if not request.env.user.has_group('universal_reports.group_universal_reports_author'):
                raise AccessDenied("Недостатньо прав для доступу до API")

            report_builder = request.env['universal.report.builder']
            fields = report_builder.get_model_fields(model_name)

            return {
                'success': True,
                'fields': fields,
                'message': f'Знайдено {len(fields)} полів'
            }
        except AccessDenied:
            return {'success': False, 'error': 'Недостатньо прав доступу'}
        except Exception as e:
            _logger.error(f"Помилка отримання полів моделі {model_name}: {str(e)}")
            return {'success': False, 'error': f'Помилка: {str(e)}'}

    @http.route('/universal_reports/execute_report', type='json', auth='user')
    def execute_report(self, report_id, filters=None, limit=None):
        """API для виконання звіту"""
        try:
            report = request.env['universal.report.builder'].browse(report_id)

            if not report.exists():
                return {'success': False, 'error': 'Звіт не знайдено'}

            # Перевірка прав доступу
            try:
                report.check_access_rights('read')
            except AccessDenied:
                return {'success': False, 'error': 'Недостатньо прав для перегляду звіту'}

            data = report.execute_report(context_filters=filters, limit=limit)

            return {
                'success': True,
                'data': data,
                'count': len(data) if isinstance(data, list) else 0,
                'message': f'Звіт виконано успішно. Записів: {len(data) if isinstance(data, list) else 0}'
            }

        except Exception as e:
            _logger.error(f"Помилка виконання звіту {report_id}: {str(e)}")
            return {'success': False, 'error': f'Помилка виконання: {str(e)}'}

    @http.route('/universal_reports/export/<int:report_id>/<format>', type='http', auth='user')
    def export_report(self, report_id, format='excel', **kwargs):
        """Експорт звіту в різних форматах"""
        try:
            report = request.env['universal.report.builder'].browse(report_id)

            if not report.exists():
                return request.not_found("Звіт не знайдено")

            # Перевірка прав доступу
            try:
                report.check_access_rights('read')
            except AccessDenied:
                return request.make_response(
                    '<h1>403 - Доступ заборонено</h1><p>Недостатньо прав для експорту звіту</p>',
                    status=403,
                    headers=[('Content-Type', 'text/html')]
                )

            # Отримання даних з урахуванням фільтрів з URL
            context_filters = []
            if kwargs.get('filters'):
                try:
                    context_filters = json.loads(kwargs['filters'])
                except json.JSONDecodeError:
                    pass

            limit = int(kwargs.get('limit', 0)) or None
            data = report.execute_report(context_filters=context_filters, limit=limit)

            # Експорт у відповідний формат
            if format == 'excel':
                file_data = base64.b64decode(report.export_to_excel(data))
                filename = f'{report.name}.xlsx'
                mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

            elif format == 'csv':
                csv_content = self._export_to_csv(report, data)
                file_data = csv_content.encode('utf-8-sig')
                filename = f'{report.name}.csv'
                mimetype = 'text/csv'

            elif format == 'json':
                json_content = self._export_to_json(report, data)
                file_data = json_content.encode('utf-8')
                filename = f'{report.name}.json'
                mimetype = 'application/json'

            elif format == 'pdf':
                # TODO: Реалізувати PDF експорт
                file_data = f"PDF експорт звіту '{report.name}' - в розробці".encode('utf-8')
                filename = f'{report.name}.pdf'
                mimetype = 'application/pdf'

            else:
                return request.not_found(f"Непідтримуваний формат: {format}")

            # Повернення файлу
            return request.make_response(
                file_data,
                headers=[
                    ('Content-Type', mimetype),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                    ('Content-Length', len(file_data))
                ]
            )

        except Exception as e:
            _logger.error(f"Помилка експорту звіту {report_id} у формат {format}: {str(e)}")
            error_html = f'''
            <html>
            <head><title>500 - Помилка сервера</title></head>
            <body>
                <h1>500 - Внутрішня помилка сервера</h1>
                <p>Помилка експорту: {str(e)}</p>
            </body>
            </html>
            '''
            return request.make_response(
                error_html,
                status=500,
                headers=[('Content-Type', 'text/html')]
            )

    @http.route('/universal_reports/preview/<int:report_id>', type='http', auth='user')
    def preview_report(self, report_id, **kwargs):
        """Попередній перегляд звіту в HTML"""
        try:
            report = request.env['universal.report.builder'].browse(report_id)

            if not report.exists():
                return request.not_found("Звіт не знайдено")

            # Отримання даних
            context_filters = []
            if kwargs.get('filters'):
                try:
                    context_filters = json.loads(kwargs['filters'])
                except json.JSONDecodeError:
                    pass

            limit = int(kwargs.get('limit', 100))  # Обмеження для попереднього перегляду
            data = report.execute_report(context_filters=context_filters, limit=limit)

            # Генерація HTML
            html_content = self._generate_html_preview(report, data,
                                                       limit < len(data) if isinstance(data, list) else False)

            return request.make_response(
                html_content,
                headers=[('Content-Type', 'text/html; charset=utf-8')]
            )

        except Exception as e:
            _logger.error(f"Помилка попереднього перегляду звіту {report_id}: {str(e)}")
            error_html = f'''
            <html>
            <head><title>500 - Помилка сервера</title></head>
            <body>
                <h1>500 - Внутрішня помилка сервера</h1>
                <p>Помилка перегляду: {str(e)}</p>
            </body>
            </html>
            '''
            return request.make_response(
                error_html,
                status=500,
                headers=[('Content-Type', 'text/html')]
            )

    @http.route('/universal_reports/quick_report', type='json', auth='user')
    def create_quick_report(self, model_name, field_names, filters=None):
        """Створення швидкого звіту"""
        try:
            if not request.env.user.has_group('universal_reports.group_universal_reports_author'):
                return {'success': False, 'error': 'Недостатньо прав для створення звітів'}

            # Створення звіту через wizard
            wizard = request.env['universal.report.wizard'].create_quick_report(
                model_name, field_names, filters
            )

            # Виконання звіту
            wizard.action_execute()

            return {
                'success': True,
                'wizard_id': wizard.id,
                'data': wizard.get_preview_data(),
                'message': 'Швидкий звіт створено успішно'
            }

        except Exception as e:
            _logger.error(f"Помилка створення швидкого звіту: {str(e)}")
            return {'success': False, 'error': str(e)}

    @http.route('/universal_reports/validate_filters', type='json', auth='user')
    def validate_filters(self, report_id, filters):
        """Валідація фільтрів"""
        try:
            report = request.env['universal.report.builder'].browse(report_id)
            if not report.exists():
                return {'success': False, 'error': 'Звіт не знайдено'}

            # Перевірка фільтрів
            valid_filters = []
            errors = []

            for filter_data in filters:
                try:
                    # Спробувати побудувати умову фільтра
                    condition = self._build_filter_condition_from_data(report, filter_data)
                    if condition:
                        valid_filters.append(filter_data)
                    else:
                        errors.append(f"Неправильний фільтр: {filter_data.get('field', 'невідоме поле')}")
                except Exception as e:
                    errors.append(f"Помилка у фільтрі {filter_data.get('field', '')}: {str(e)}")

            return {
                'success': True,
                'valid_filters': valid_filters,
                'errors': errors,
                'message': f'Валідних фільтрів: {len(valid_filters)}, помилок: {len(errors)}'
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _build_filter_condition_from_data(self, report, filter_data):
        """Побудувати умову фільтра з даних"""
        try:
            field_name = filter_data.get('field')
            operator = filter_data.get('operator', '=')
            value = filter_data.get('value')

            if not field_name or not value:
                return None

            # Перевіряємо чи існує поле в моделі
            model_obj = request.env[report.model_name]
            if field_name not in model_obj._fields:
                return None

            field = model_obj._fields[field_name]

            # Конвертуємо значення відповідно до типу поля
            if field.type == 'boolean':
                value = str(value).lower() in ('true', '1', 'yes', 'так')
            elif field.type in ('integer', 'float'):
                value = float(value) if field.type == 'float' else int(value)
            elif field.type == 'many2one':
                if isinstance(value, str) and value.isdigit():
                    value = int(value)
                else:
                    return None

            return (field_name, operator, value)

        except (ValueError, TypeError, KeyError):
            return None

    def _export_to_csv(self, report, data):
        """Експорт даних у CSV"""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        # Заголовки
        visible_fields = report.field_ids.filtered('visible').sorted('sequence')
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
                    self._write_csv_record(writer, record, visible_fields)

                # Порожній рядок
                writer.writerow([''] * len(headers))
        else:
            # Звичайні дані
            for record in data:
                self._write_csv_record(writer, record, visible_fields)

        return output.getvalue()

    def _write_csv_record(self, writer, record, visible_fields):
        """Запис одного запису у CSV"""
        row = []
        for field in visible_fields:
            value = record.get(field.field_name, '')
            if isinstance(value, (list, tuple)) and len(value) > 1:
                value = value[1]  # Для many2one полів

            # Форматування значення
            if hasattr(field, 'get_formatted_value'):
                formatted_value = field.get_formatted_value(value)
            else:
                formatted_value = str(value) if value is not None else ''

            row.append(formatted_value)
        writer.writerow(row)

    def _export_to_json(self, report, data):
        """Експорт даних у JSON"""
        visible_fields = report.field_ids.filtered('visible').sorted('sequence')

        export_data = {
            'report_info': {
                'name': report.name,
                'model': report.model_name,
                'generated_at': fields.Datetime.now().isoformat(),
                'total_records': len(data) if isinstance(data, list) else 0
            },
            'fields': [
                {
                    'name': f.field_name,
                    'label': f.field_label or f.field_name,
                    'type': f.field_type,
                    'format': f.format_type
                } for f in visible_fields
            ],
            'data': data
        }

        return json.dumps(export_data, default=str, ensure_ascii=False, indent=2)

    def _generate_html_preview(self, report, data, has_more=False):
        """Генерація HTML для попереднього перегляду"""
        visible_fields = report.field_ids.filtered('visible').sorted('sequence')

        html = f"""
        <!DOCTYPE html>
        <html lang="uk">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{report.name}</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
                .report-header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem; }}
                .group-header {{ background-color: #f8f9fa; font-weight: bold; }}
                .table-hover tbody tr:hover {{ background-color: rgba(0,0,0,.075); }}
                .limited-notice {{ background-color: #fff3cd; border: 1px solid #ffeaa7; }}
            </style>
        </head>
        <body>
            <div class="report-header text-center">
                <h1>{report.name}</h1>
                <p class="mb-0">Модель: {report.model_id.name}</p>
                <small>Згенеровано: {fields.Datetime.now().strftime('%d.%m.%Y о %H:%M')}</small>
            </div>

            <div class="container-fluid mt-4">
                {'<div class="alert alert-warning limited-notice" role="alert"><strong>Увага!</strong> Показано обмежену кількість записів для попереднього перегляду.</div>' if has_more else ''}

                <div class="row mb-3">
                    <div class="col">
                        <div class="d-flex justify-content-between align-items-center">
                            <h5 class="mb-0">Результати звіту</h5>
                            <span class="badge bg-primary">Записів: {len(data) if isinstance(data, list) else 0}</span>
                        </div>
                    </div>
                </div>

                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
        """

        # Заголовки таблиці
        for field in visible_fields:
            html += f'<th scope="col">{field.field_label or field.field_name}</th>'

        html += '</tr></thead><tbody>'

        # Дані таблиці
        if isinstance(data, list) and data and 'group_name' in data[0]:
            # Групировані дані
            for group in data:
                html += f'''
                <tr class="group-header">
                    <td colspan="{len(visible_fields)}">
                        <i class="fas fa-folder"></i> {group['group_name']} 
                        <span class="badge bg-secondary">{group['group_count']} записів</span>
                    </td>
                </tr>
                '''
                for record in group['records']:
                    html += '<tr>'
                    for field in visible_fields:
                        value = record.get(field.field_name, '')
                        if isinstance(value, (list, tuple)) and len(value) > 1:
                            value = value[1]

                        formatted_value = field.get_formatted_value(value) if hasattr(field,
                                                                                      'get_formatted_value') else str(
                            value)
                        html += f'<td>{formatted_value}</td>'
                    html += '</tr>'
        else:
            # Звичайні дані
            for record in data if isinstance(data, list) else []:
                html += '<tr>'
                for field in visible_fields:
                    value = record.get(field.field_name, '')
                    if isinstance(value, (list, tuple)) and len(value) > 1:
                        value = value[1]

                    formatted_value = field.get_formatted_value(value) if hasattr(field,
                                                                                  'get_formatted_value') else str(value)
                    html += f'<td>{formatted_value}</td>'
                html += '</tr>'

        html += '''
                        </tbody>
                    </table>
                </div>
            </div>

            <footer class="text-center text-muted mt-4 py-3">
                <small>Згенеровано системою звітності Odoo</small>
            </footer>
        </body>
        </html>
        '''

        return html