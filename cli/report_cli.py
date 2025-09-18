#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Інтерфейс командного рядка для універсальних звітів Odoo
"""

import sys
import os
import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
import base64

# Додаємо шлях до Odoo
try:
    import odoo
    from odoo import api, SUPERUSER_ID
    from odoo.exceptions import UserError, ValidationError
except ImportError:
    print("❌ Помилка: Odoo не знайдено в PATH")
    print("Встановіть Odoo або додайте шлях до Odoo в PYTHONPATH")
    sys.exit(1)

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('universal_reports_cli.log')
    ]
)
logger = logging.getLogger(__name__)


class ReportCLI:
    """Інтерфейс командного рядка для генератора звітів"""

    def __init__(self, database, user_id=SUPERUSER_ID):
        self.database = database
        self.user_id = user_id
        self.registry = None
        self.env = None

    def __enter__(self):
        """Контекстний менеджер для підключення до БД"""
        try:
            self.registry = odoo.registry(self.database)
            self.env = api.Environment(self.registry.cursor(), self.user_id, {})
            return self
        except Exception as e:
            logger.error(f"Помилка підключення до БД '{self.database}': {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Закриття підключення"""
        if self.env:
            self.env.cr.close()

    def list_reports(self, template_only=False, active_only=True):
        """Показати список доступних звітів"""
        try:
            domain = []
            if template_only:
                domain.append(('is_template', '=', True))
            if active_only:
                domain.append(('active', '=', True))

            reports = self.env['universal.report.builder'].search(domain)

            if not reports:
                print("📋 Звіти не знайдені")
                return

            print(f"📋 Знайдено звітів: {len(reports)}")
            print("-" * 80)

            for report in reports:
                status = "🟢" if report.active else "🔴"
                template_mark = "📄" if report.is_template else "📊"

                print(f"{status} {template_mark} {report.name}")
                print(f"   ID: {report.id}")
                print(f"   Модель: {report.model_id.name} ({report.model_name})")
                print(f"   Полів: {len(report.field_ids.filtered('visible'))}")
                if report.last_execution:
                    print(f"   Останнє виконання: {report.last_execution}")
                    print(f"   Записів: {report.result_count}")
                print("-" * 80)

        except Exception as e:
            logger.error(f"Помилка отримання списку звітів: {e}")
            print(f"❌ Помилка: {e}")
            return False

    def execute_report(self, report_identifier, output_file=None, export_format='excel',
                       filters=None, limit=None, preview=False):
        """Виконання звіту"""
        try:
            # Пошук звіту за ID або назвою
            if str(report_identifier).isdigit():
                report = self.env['universal.report.builder'].browse(int(report_identifier))
            else:
                report = self.env['universal.report.builder'].search([
                    ('name', '=', report_identifier)
                ], limit=1)

            if not report:
                print(f"❌ Звіт '{report_identifier}' не знайдено")
                return False

            print(f"🚀 Виконується звіт: {report.name}")
            print(f"   Модель: {report.model_id.name}")

            # Підготовка фільтрів
            context_filters = []
            if filters:
                if isinstance(filters, str):
                    try:
                        context_filters = json.loads(filters)
                    except json.JSONDecodeError:
                        print("❌ Неправильний формат JSON для фільтрів")
                        return False
                elif isinstance(filters, list):
                    context_filters = filters

            # Виконання звіту
            start_time = datetime.now()
            data = report.execute_report(context_filters=context_filters, limit=limit)
            execution_time = (datetime.now() - start_time).total_seconds()

            record_count = len(data) if isinstance(data, list) else 0
            print(f"✅ Звіт виконано успішно")
            print(f"   Записів: {record_count}")
            print(f"   Час виконання: {execution_time:.2f} сек")

            if preview:
                self._show_preview(data, report)
                return True

            # Експорт результатів
            if output_file:
                success = self._export_data(data, report, export_format, output_file)
                return success
            else:
                # Виводимо на екран (обмежено)
                self._print_results(data, report, limit=20)
                return True

        except Exception as e:
            logger.error(f"Помилка виконання звіту: {e}")
            print(f"❌ Помилка виконання звіту: {e}")
            return False

    def create_report_from_config(self, config_file):
        """Створення звіту з конфігураційного файлу"""
        try:
            config_path = Path(config_file)
            if not config_path.exists():
                print(f"❌ Файл конфігурації не знайдено: {config_file}")
                return False

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Валідація конфігурації
            required_fields = ['name', 'model', 'fields']
            for field in required_fields:
                if field not in config:
                    print(f"❌ Відсутнє обов'язкове поле в конфігурації: {field}")
                    return False

            # Пошук моделі
            model = self.env['ir.model'].search([('model', '=', config['model'])], limit=1)
            if not model:
                print(f"❌ Модель не знайдена: {config['model']}")
                return False

            print(f"🔨 Створюється звіт: {config['name']}")

            # Створення звіту
            report_data = {
                'name': config['name'],
                'description': config.get('description', ''),
                'model_id': model.id,
                'is_template': config.get('is_template', False),
                'format_type': config.get('format_type', 'table'),
            }

            report = self.env['universal.report.builder'].create(report_data)

            # Додавання полів
            for seq, field_config in enumerate(config['fields'], 1):
                field_data = {
                    'report_id': report.id,
                    'sequence': seq,
                    'field_name': field_config['name'],
                    'field_label': field_config.get('label', field_config['name']),
                    'visible': field_config.get('visible', True),
                    'format_type': field_config.get('format', 'text'),
                    'aggregation': field_config.get('aggregation', 'none'),
                }
                self.env['universal.report.field'].create(field_data)

            # Додавання фільтрів
            if 'filters' in config:
                for seq, filter_config in enumerate(config['filters'], 1):
                    filter_data = {
                        'report_id': report.id,
                        'sequence': seq,
                        'name': filter_config.get('name', f'Фільтр {seq}'),
                        'field_name': filter_config['field'],
                        'operator': filter_config.get('operator', '='),
                        'value': filter_config.get('value', ''),
                        'active': filter_config.get('active', True),
                    }
                    self.env['universal.report.filter'].create(filter_data)

            # Збереження змін
            self.env.cr.commit()

            print(f"✅ Звіт створено успішно (ID: {report.id})")
            return report.id

        except Exception as e:
            self.env.cr.rollback()
            logger.error(f"Помилка створення звіту: {e}")
            print(f"❌ Помилка створення звіту: {e}")
            return False

    def schedule_report(self, report_identifier, schedule_config):
        """Створення планувальника для звіту"""
        try:
            # Пошук звіту
            if str(report_identifier).isdigit():
                report = self.env['universal.report.builder'].browse(int(report_identifier))
            else:
                report = self.env['universal.report.builder'].search([
                    ('name', '=', report_identifier)
                ], limit=1)

            if not report:
                print(f"❌ Звіт '{report_identifier}' не знайдено")
                return False

            # Створення планувальника
            scheduler_data = {
                'name': schedule_config.get('name', f'Планувальник для {report.name}'),
                'report_id': report.id,
                'interval_type': schedule_config.get('interval_type', 'days'),
                'interval_number': schedule_config.get('interval_number', 1),
                'execution_time': schedule_config.get('execution_time', 9.0),
                'email_recipients': schedule_config.get('email_recipients', ''),
                'attach_report': schedule_config.get('attach_report', True),
                'active': schedule_config.get('active', True),
            }

            scheduler = self.env['universal.report.scheduler'].create(scheduler_data)
            self.env.cr.commit()

            print(f"✅ Планувальник створено (ID: {scheduler.id})")
            print(f"   Інтервал: кожні {scheduler.interval_number} {scheduler.interval_type}")
            print(f"   Час виконання: {scheduler.execution_time}")

            return scheduler.id

        except Exception as e:
            self.env.cr.rollback()
            logger.error(f"Помилка створення планувальника: {e}")
            print(f"❌ Помилка створення планувальника: {e}")
            return False

    def _export_data(self, data, report, export_format, output_file):
        """Експорт даних у файл"""
        try:
            output_path = Path(output_file)

            if export_format == 'excel':
                file_data = report.export_to_excel(data)
                with open(output_path, 'wb') as f:
                    f.write(base64.b64decode(file_data))

            elif export_format == 'csv':
                csv_content = self._export_to_csv(data, report)
                with open(output_path, 'w', encoding='utf-8-sig') as f:
                    f.write(csv_content)

            elif export_format == 'json':
                json_content = self._export_to_json(data, report)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(json_content)

            else:
                print(f"❌ Непідтримуваний формат експорту: {export_format}")
                return False

            file_size = output_path.stat().st_size
            print(f"💾 Файл збережено: {output_path}")
            print(f"   Розмір: {file_size:,} байт")

            return True

        except Exception as e:
            logger.error(f"Помилка експорту: {e}")
            print(f"❌ Помилка експорту: {e}")
            return False

    def _export_to_csv(self, data, report):
        """Експорт у CSV"""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', quotechar='"')

        # Заголовки
        visible_fields = report.field_ids.filtered('visible').sorted('sequence')
        headers = [f.field_label or f.field_name for f in visible_fields]
        writer.writerow(headers)

        # Дані
        for record in data:
            row = []
            for field in visible_fields:
                value = record.get(field.field_name, '')
                if isinstance(value, (list, tuple)) and len(value) > 1:
                    value = value[1]
                row.append(str(value) if value is not None else '')
            writer.writerow(row)

        return output.getvalue()

    def _export_to_json(self, data, report):
        """Експорт у JSON"""
        export_data = {
            'report_info': {
                'name': report.name,
                'model': report.model_name,
                'generated_at': datetime.now().isoformat(),
                'total_records': len(data) if isinstance(data, list) else 0
            },
            'data': data
        }
        return json.dumps(export_data, default=str, ensure_ascii=False, indent=2)

    def _show_preview(self, data, report, limit=10):
        """Показати попередній перегляд"""
        visible_fields = report.field_ids.filtered('visible').sorted('sequence')

        print(f"\n📋 Попередній перегляд звіту: {report.name}")
        print("=" * 80)

        # Заголовки
        headers = [f.field_label or f.field_name for f in visible_fields]
        print(" | ".join(f"{h[:15]:15}" for h in headers))
        print("-" * 80)

        # Дані (обмежено)
        display_data = data[:limit] if isinstance(data, list) else []

        for record in display_data:
            row = []
            for field in visible_fields:
                value = record.get(field.field_name, '')
                if isinstance(value, (list, tuple)) and len(value) > 1:
                    value = value[1]

                str_value = str(value) if value is not None else ''
                row.append(str_value[:15])

            print(" | ".join(f"{cell:15}" for cell in row))

        total_records = len(data) if isinstance(data, list) else 0
        if total_records > limit:
            print(f"\n... і ще {total_records - limit} записів")

        print(f"\nВсього записів: {total_records}")

    def _print_results(self, data, report, limit=20):
        """Виведення результатів на екран"""
        self._show_preview(data, report, limit)


def create_sample_config():
    """Створити приклад конфігураційного файлу"""
    sample_config = {
        "name": "Звіт по партнерах (приклад)",
        "description": "Приклад конфігурації звіту",
        "model": "res.partner",
        "format_type": "table",
        "is_template": False,
        "fields": [
            {
                "name": "name",
                "label": "Назва",
                "visible": True,
                "format": "text"
            },
            {
                "name": "email",
                "label": "Email",
                "visible": True,
                "format": "text"
            },
            {
                "name": "phone",
                "label": "Телефон",
                "visible": True,
                "format": "text"
            },
            {
                "name": "is_company",
                "label": "Компанія",
                "visible": True,
                "format": "boolean"
            }
        ],
        "filters": [
            {
                "name": "Тільки активні",
                "field": "active",
                "operator": "=",
                "value": "True",
                "active": True
            }
        ]
    }

    with open('sample_report_config.json', 'w', encoding='utf-8') as f:
        json.dump(sample_config, f, ensure_ascii=False, indent=2)

    print("📝 Створено приклад конфігурації: sample_report_config.json")


def main():
    """Головна функція CLI"""
    parser = argparse.ArgumentParser(
        description='Універсальний генератор звітів Odoo - CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Приклади використання:

  # Показати всі звіти
  python report_cli.py my_database list

  # Виконати звіт за ID
  python report_cli.py my_database execute 1 --format excel --output report.xlsx

  # Виконати звіт за назвою з фільтрами
  python report_cli.py my_database execute "Звіт по партнерах" \\
    --filters '[{"field": "active", "operator": "=", "value": true}]' \\
    --output partners.csv --format csv

  # Створити звіт з конфігурації
  python report_cli.py my_database create --config report_config.json

  # Попередній перегляд
  python report_cli.py my_database execute 1 --preview

  # Створити приклад конфігурації
  python report_cli.py sample-config
        """)

    parser.add_argument('database', help='Назва бази даних Odoo')
    parser.add_argument('command', choices=['list', 'execute', 'create', 'schedule', 'sample-config'],
                        help='Команда для виконання')

    # Загальні параметри
    parser.add_argument('--user-id', type=int, default=SUPERUSER_ID,
                        help='ID користувача (за замовчуванням: супер користувач)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Детальний вивід')

    # Параметри для list
    parser.add_argument('--templates-only', action='store_true',
                        help='Показати тільки шаблони')
    parser.add_argument('--include-inactive', action='store_true',
                        help='Включити неактивні звіти')

    # Параметри для execute
    parser.add_argument('report_id', nargs='?',
                        help='ID або назва звіту для виконання')
    parser.add_argument('--format', choices=['excel', 'csv', 'json'],
                        default='excel', help='Формат експорту')
    parser.add_argument('--output', '-o', help='Файл для збереження результату')
    parser.add_argument('--filters', help='JSON з фільтрами')
    parser.add_argument('--limit', type=int, help='Обмеження кількості записів')
    parser.add_argument('--preview', action='store_true',
                        help='Тільки попередній перегляд (не зберігати файл)')

    # Параметри для create
    parser.add_argument('--config', help='Файл конфігурації звіту (JSON)')

    # Параметри для schedule
    parser.add_argument('--schedule-config', help='Файл конфігурації планувальника (JSON)')

    args = parser.parse_args()

    # Налаштування логування
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Спеціальна команда для створення прикладу
    if args.command == 'sample-config':
        create_sample_config()
        return 0

    # Перевірка параметрів для різних команд
    if args.command == 'execute' and not args.report_id:
        parser.error("Команда 'execute' потребує report_id")

    if args.command == 'create' and not args.config:
        parser.error("Команда 'create' потребує --config")

    if args.command == 'schedule' and not args.schedule_config:
        parser.error("Команда 'schedule' потребує --schedule-config")

    # Виконання команди
    try:
        with ReportCLI(args.database, args.user_id) as cli:
            success = False

            if args.command == 'list':
                success = cli.list_reports(
                    template_only=args.templates_only,
                    active_only=not args.include_inactive
                )

            elif args.command == 'execute':
                success = cli.execute_report(
                    report_identifier=args.report_id,
                    output_file=args.output,
                    export_format=args.format,
                    filters=args.filters,
                    limit=args.limit,
                    preview=args.preview
                )

            elif args.command == 'create':
                success = cli.create_report_from_config(args.config)

            elif args.command == 'schedule':
                with open(args.schedule_config, 'r', encoding='utf-8') as f:
                    schedule_config = json.load(f)
                success = cli.schedule_report(args.report_id, schedule_config)

            return 0 if success else 1

    except KeyboardInterrupt:
        print("\n⏹️  Операцію перервано користувачем")
        return 130
    except Exception as e:
        logger.error(f"Критична помилка: {e}")
        print(f"💥 Критична помилка: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())