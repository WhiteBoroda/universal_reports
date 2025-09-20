# -*- coding: utf-8 -*-
{
    'name': 'Універсальний генератор звітів',
    'version': '17.0.1.0.3',
    'category': 'Звітність',
    'summary': 'Конструктор звітів як у 1С',
    'description': '''

                                              Універсальний генератор звітів для Odoo 17

                                              Функціонал:
                                              - Створення довільних звітів по будь-яким моделям
                                              - Гнучке налаштування групувань та сортувань
                                              - Підтримка фільтрів та умов
                                              - Експорт у різні формати (Excel, PDF, CSV)
                                              - Збереження шаблонів звітів
                                              - Візуальний конструктор звітів
                                              - Планувальник автоматичного виконання
                                          ''',
    'author': 'HD Digital Solution',
    'website': 'https://github.com/WhiteBoroda/universal_reports.git',
    'depends': ['base', 'web', 'mail'],
    'external_dependencies': {'python': ['xlsxwriter', 'reportlab']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/report_templates.xml',
        'views/report_scheduler_views.xml',
        'views/report_builder_views.xml',
        'wizard/report_wizard_views.xml',
        'wizard/export_wizard_views.xml',
        'views/menu_views.xml'
    ],
    'assets': {
        'web.assets_backend': [
            'universal_reports/static/src/js/**/*',
            'universal_reports/static/src/css/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'price': 0,
    'currency': 'EUR',
}