/** @odoo-module */

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class ReportBuilderWidget extends Component {
    /**
     * Основний компонент конструктора звітів
     */

    setup() {
        // Сервіси
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.rpc = useService("rpc");

        // Стан компонента
        this.state = useState({
            // Моделі та поля
            selectedModel: null,
            availableModels: [],
            availableFields: [],

            // Налаштування звіту
            selectedFields: [],
            filters: [],
            groups: [],
            sorts: [],

            // Результати
            reportData: null,
            reportCount: 0,

            // UI стан
            loading: false,
            previewMode: false,
            currentStep: 1,

            // Помилки
            errors: []
        });

        // Завантажуємо початкові дані
        onWillStart(this.loadInitialData);
    }

    async loadInitialData() {
        /**
         * Завантаження початкових даних (моделі)
         */
        try {
            this.state.loading = true;

            this.state.availableModels = await this.orm.searchRead(
                "ir.model",
                [['transient', '=', false], ['abstract', '=', false]],
                ['id', 'name', 'model'],
                { order: 'name' }
            );

        } catch (error) {
            this.showError(_t("Помилка завантаження моделей"), error);
        } finally {
            this.state.loading = false;
        }
    }

    async onModelChange(modelId) {
        /**
         * Обробка зміни моделі
         */
        if (!modelId) {
            this.clearModelData();
            return;
        }

        this.state.loading = true;
        this.state.errors = [];

        try {
            const model = this.state.availableModels.find(m => m.id === modelId);
            if (!model) {
                throw new Error(_t("Модель не знайдена"));
            }

            this.state.selectedModel = model;

            // Отримуємо поля моделі через RPC
            const result = await this.rpc("/universal_reports/get_model_fields", {
                model_name: model.model
            });

            if (result.success) {
                this.state.availableFields = result.fields;
                this.clearReportData();
                this.showSuccess(result.message || _t("Поля завантажено успішно"));
            } else {
                throw new Error(result.error);
            }

        } catch (error) {
            this.showError(_t("Помилка завантаження полів моделі"), error);
        } finally {
            this.state.loading = false;
        }
    }

    addField(field) {
        /**
         * Додавання поля до звіту
         */
        if (!this.state.selectedFields.find(f => f.name === field.name)) {
            this.state.selectedFields.push({
                name: field.name,
                label: field.string,
                type: field.type,
                visible: true,
                sequence: this.state.selectedFields.length + 1,
                format_type: this.guessFormatType(field.type),
                aggregation: 'none'
            });

            this.showSuccess(_t("Поле додано: ") + field.string);
        } else {
            this.showWarning(_t("Поле вже додано до звіту"));
        }
    }

    removeField(fieldName) {
        /**
         * Видалення поля зі звіту
         */
        const index = this.state.selectedFields.findIndex(f => f.name === fieldName);
        if (index >= 0) {
            const removedField = this.state.selectedFields.splice(index, 1)[0];
            this.showInfo(_t("Поле видалено: ") + removedField.label);
        }
    }

    moveField(fieldName, direction) {
        /**
         * Переміщення поля вгору/вниз
         */
        const fields = this.state.selectedFields;
        const index = fields.findIndex(f => f.name === fieldName);

        if (index === -1) return;

        const newIndex = direction === 'up' ? index - 1 : index + 1;

        if (newIndex >= 0 && newIndex < fields.length) {
            [fields[index], fields[newIndex]] = [fields[newIndex], fields[index]];

            // Оновлюємо послідовність
            fields.forEach((field, idx) => {
                field.sequence = idx + 1;
            });
        }
    }

    addFilter() {
        /**
         * Додавання нового фільтра
         */
        this.state.filters.push({
            id: Date.now(), // Унікальний ID для видалення
            field: '',
            field_type: 'char',
            operator: '=',
            value: '',
            active: true
        });
    }

    removeFilter(filterId) {
        /**
         * Видалення фільтра
         */
        const index = this.state.filters.findIndex(f => f.id === filterId);
        if (index >= 0) {
            this.state.filters.splice(index, 1);
        }
    }

    updateFilter(filterId, property, value) {
        /**
         * Оновлення властивості фільтра
         */
        const filter = this.state.filters.find(f => f.id === filterId);
        if (filter) {
            filter[property] = value;

            // Автоматичне визначення типу поля
            if (property === 'field') {
                const field = this.state.availableFields.find(f => f.name === value);
                if (field) {
                    filter.field_type = field.type;
                }
            }
        }
    }

    addSort() {
        /**
         * Додавання сортування
         */
        this.state.sorts.push({
            id: Date.now(),
            field: '',
            direction: 'asc'
        });
    }

    removeSort(sortId) {
        /**
         * Видалення сортування
         */
        const index = this.state.sorts.findIndex(s => s.id === sortId);
        if (index >= 0) {
            this.state.sorts.splice(index, 1);
        }
    }

    addGroup() {
        /**
         * Додавання групування
         */
        this.state.groups.push({
            id: Date.now(),
            field: '',
            show_totals: true
        });
    }

    removeGroup(groupId) {
        /**
         * Видалення групування
         */
        const index = this.state.groups.findIndex(g => g.id === groupId);
        if (index >= 0) {
            this.state.groups.splice(index, 1);
        }
    }

    async executeReport() {
        /**
         * Виконання звіту
         */
        if (!this.validateReportSettings()) {
            return;
        }

        this.state.loading = true;
        this.state.errors = [];

        try {
            // Створюємо тимчасовий звіт
            const reportData = await this.createTempReport();

            // Виконуємо звіт
            const result = await this.rpc("/universal_reports/execute_report", {
                report_id: reportData.id,
                filters: this.prepareFilters(),
                limit: this.state.previewMode ? 100 : null
            });

            if (result.success) {
                this.state.reportData = result.data;
                this.state.reportCount = result.count;
                this.showSuccess(result.message);

                // Переходимо до результатів
                this.state.currentStep = 4;
            } else {
                throw new Error(result.error);
            }

        } catch (error) {
            this.showError(_t("Помилка виконання звіту"), error);
        } finally {
            this.state.loading = false;
        }
    }

    async exportReport(format) {
        /**
         * Експорт звіту
         */
        if (!this.state.reportData) {
            this.showWarning(_t("Спочатку виконайте звіт"));
            return;
        }

        try {
            const reportData = await this.createTempReport();
            const filters = encodeURIComponent(JSON.stringify(this.prepareFilters()));
            const url = `/universal_reports/export/${reportData.id}/${format}?filters=${filters}`;

            // Створюємо посилання для завантаження
            const link = document.createElement('a');
            link.href = url;
            link.download = `report.${format}`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showSuccess(_t("Звіт експортовано в ") + format.toUpperCase());

        } catch (error) {
            this.showError(_t("Помилка експорту"), error);
        }
    }

    async saveAsTemplate() {
        /**
         * Збереження як шаблон
         */
        if (!this.validateReportSettings()) {
            return;
        }

        const templateName = prompt(_t("Введіть назву шаблону:"));
        if (!templateName) return;

        try {
            const reportData = {
                name: templateName,
                model_id: this.state.selectedModel.id,
                is_template: true,
                field_ids: this.prepareFields(),
                filter_ids: this.prepareFiltersForSave()
            };

            await this.orm.create("universal.report.builder", [reportData]);
            this.showSuccess(_t("Шаблон збережено"));

        } catch (error) {
            this.showError(_t("Помилка збереження шаблону"), error);
        }
    }

    // === Допоміжні методи ===

    validateReportSettings() {
        /**
         * Валідація налаштувань звіту
         */
        this.state.errors = [];

        if (!this.state.selectedModel) {
            this.state.errors.push(_t("Оберіть модель даних"));
        }

        if (this.state.selectedFields.length === 0) {
            this.state.errors.push(_t("Додайте хоча б одне поле до звіту"));
        }

        // Перевірка фільтрів
        const invalidFilters = this.state.filters.filter(f =>
            f.active && f.field && !f.value && f.operator !== '!='
        );

        if (invalidFilters.length > 0) {
            this.state.errors.push(_t("Заповніть значення для всіх активних фільтрів"));
        }

        if (this.state.errors.length > 0) {
            this.showError(_t("Виправте помилки перед продовженням"), this.state.errors.join('; '));
            return false;
        }

        return true;
    }

    async createTempReport() {
        /**
         * Створення тимчасового звіту
         */
        const reportData = {
            name: _t("Тимчасовий звіт"),
            model_id: this.state.selectedModel.id,
            field_ids: this.prepareFields(),
            filter_ids: this.prepareFiltersForSave()
        };

        const reportId = await this.orm.create("universal.report.builder", [reportData]);
        return { id: reportId };
    }

    prepareFields() {
        /**
         * Підготовка полів для збереження
         */
        return this.state.selectedFields.map((field, index) => [0, 0, {
            field_name: field.name,
            field_label: field.label,
            field_type: field.type,
            visible: field.visible,
            sequence: index + 1,
            format_type: field.format_type,
            aggregation: field.aggregation
        }]);
    }

    prepareFilters() {
        /**
         * Підготовка фільтрів для виконання
         */
        return this.state.filters
            .filter(f => f.active && f.field && f.value)
            .map(f => ({
                field: f.field,
                operator: f.operator,
                value: f.value
            }));
    }

    prepareFiltersForSave() {
        /**
         * Підготовка фільтрів для збереження
         */
        return this.state.filters
            .filter(f => f.field)
            .map((f, index) => [0, 0, {
                name: _t("Фільтр ") + (index + 1),
                field_name: f.field,
                operator: f.operator,
                value: f.value,
                active: f.active,
                sequence: index + 1
            }]);
    }

    guessFormatType(fieldType) {
        /**
         * Автоматичне визначення типу форматування
         */
        const typeMap = {
            'char': 'text',
            'text': 'text',
            'integer': 'number',
            'float': 'number',
            'monetary': 'currency',
            'date': 'date',
            'datetime': 'datetime',
            'boolean': 'boolean',
            'selection': 'selection'
        };

        return typeMap[fieldType] || 'text';
    }

    clearModelData() {
        /**
         * Очищення даних при зміні моделі
         */
        this.state.selectedModel = null;
        this.state.availableFields = [];
        this.clearReportData();
    }

    clearReportData() {
        /**
         * Очищення даних звіту
         */
        this.state.selectedFields = [];
        this.state.filters = [];
        this.state.groups = [];
        this.state.sorts = [];
        this.state.reportData = null;
        this.state.reportCount = 0;
        this.state.currentStep = 1;
    }

    goToStep(step) {
        /**
         * Перехід до певного кроку
         */
        this.state.currentStep = step;
    }

    // === Повідомлення ===

    showSuccess(message) {
        this.notification.add(message, { type: "success", sticky: false });
    }

    showError(title, error = null) {
        const message = error instanceof Error ? error.message : (error || title);
        this.notification.add(message, { type: "danger", sticky: true });
    }

    showWarning(message) {
        this.notification.add(message, { type: "warning", sticky: false });
    }

    showInfo(message) {
        this.notification.add(message, { type: "info", sticky: false });
    }
}

// Реєстрація компонента
ReportBuilderWidget.template = "ReportBuilderWidget";

registry.category("actions").add("universal_reports.report_builder_action", ReportBuilderWidget);