/** @odoo-module */

import { ReportBuilderWidget } from "./report_builder";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

/**
 * Розширений конструктор звітів з додатковими можливостями
 */
export class ReportBuilderExtended extends ReportBuilderWidget {

    setup() {
        super.setup();

        // Додаткові стани для розширеної функціональності
        Object.assign(this.state, {
            // Додаткові налаштування
            advancedMode: false,
            autoRefresh: false,
            refreshInterval: 30000,

            // Історія дій
            history: [],
            historyIndex: -1,

            // Налаштування відображення
            viewSettings: {
                showLineNumbers: true,
                showFieldTypes: true,
                compactMode: false,
                darkTheme: false
            },

            // Кешування
            cachedResults: new Map(),
            lastCacheKey: null,

            // Статистика
            executionStats: {
                totalExecutions: 0,
                avgExecutionTime: 0,
                lastExecutionTime: 0
            }
        });

        // Ініціалізація автооновлення
        this.refreshTimer = null;
    }

    // === Розширена функціональність ===

    toggleAdvancedMode() {
        /**
         * Перемикання розширеного режиму
         */
        this.state.advancedMode = !this.state.advancedMode;
        this.showInfo(
            this.state.advancedMode
                ? _t("Розширений режим увімкнено")
                : _t("Розширений режим вимкнено")
        );
    }

    async duplicateField(fieldName) {
        /**
         * Дублювання поля з можливістю змінити налаштування
         */
        const originalField = this.state.selectedFields.find(f => f.name === fieldName);
        if (!originalField) return;

        const duplicatedField = {
            ...originalField,
            label: originalField.label + " (копія)",
            sequence: this.state.selectedFields.length + 1
        };

        this.state.selectedFields.push(duplicatedField);
        this.addToHistory('duplicate_field', { field: fieldName });
        this.showSuccess(_t("Поле продубльовано"));
    }

    async bulkAddFields() {
        /**
         * Масове додавання полів
         */
        const availableFields = this.state.availableFields.filter(
            af => !this.state.selectedFields.find(sf => sf.name === af.name)
        );

        if (availableFields.length === 0) {
            this.showWarning(_t("Всі поля вже додані"));
            return;
        }

        // Відкриваємо діалог вибору полів
        this.dialog.add(BulkFieldSelectionDialog, {
            availableFields,
            onConfirm: (selectedFields) => {
                selectedFields.forEach((field, index) => {
                    this.state.selectedFields.push({
                        name: field.name,
                        label: field.string,
                        type: field.type,
                        visible: true,
                        sequence: this.state.selectedFields.length + index + 1,
                        format_type: this.guessFormatType(field.type),
                        aggregation: 'none'
                    });
                });

                this.addToHistory('bulk_add_fields', { count: selectedFields.length });
                this.showSuccess(_t("Додано полів: ") + selectedFields.length);
            }
        });
    }

    async smartFieldRecommendation() {
        /**
         * Розумні рекомендації полів на основі моделі
         */
        if (!this.state.selectedModel) return;

        const modelName = this.state.selectedModel.model;
        const recommendations = await this.getFieldRecommendations(modelName);

        if (recommendations.length > 0) {
            this.dialog.add(FieldRecommendationDialog, {
                recommendations,
                onAccept: (fields) => {
                    fields.forEach(field => this.addField(field));
                }
            });
        } else {
            this.showInfo(_t("Немає рекомендацій для цієї моделі"));
        }
    }

    async getFieldRecommendations(modelName) {
        /**
         * Отримання рекомендацій полів
         */
        const commonFields = {
            'res.partner': ['name', 'email', 'phone', 'city', 'country_id'],
            'sale.order': ['name', 'partner_id', 'date_order', 'amount_total', 'state'],
            'product.product': ['name', 'default_code', 'list_price', 'qty_available', 'categ_id'],
            'account.move': ['name', 'partner_id', 'invoice_date', 'amount_total', 'state'],
            'stock.picking': ['name', 'partner_id', 'scheduled_date', 'state', 'location_id'],
            'hr.employee': ['name', 'job_id', 'department_id', 'work_email', 'work_phone']
        };

        const recommendedFieldNames = commonFields[modelName] || [];

        return this.state.availableFields.filter(field =>
            recommendedFieldNames.includes(field.name) &&
            !this.state.selectedFields.find(sf => sf.name === field.name)
        );
    }

    async executeWithCache() {
        /**
         * Виконання з кешуванням результатів
         */
        const cacheKey = this.generateCacheKey();

        if (this.state.cachedResults.has(cacheKey)) {
            this.state.reportData = this.state.cachedResults.get(cacheKey);
            this.state.reportCount = Array.isArray(this.state.reportData) ? this.state.reportData.length : 0;
            this.showInfo(_t("Завантажено з кешу"));
            return;
        }

        const startTime = Date.now();
        await this.executeReport();
        const executionTime = Date.now() - startTime;

        // Зберігаємо в кеш
        if (this.state.reportData) {
            this.state.cachedResults.set(cacheKey, this.state.reportData);
            this.state.lastCacheKey = cacheKey;
        }

        // Оновлюємо статистику
        this.updateExecutionStats(executionTime);
    }

    generateCacheKey() {
        /**
         * Генерація ключа для кешу
         */
        return JSON.stringify({
            model: this.state.selectedModel?.model,
            fields: this.state.selectedFields.map(f => f.name),
            filters: this.prepareFilters(),
            sorts: this.state.sorts.filter(s => s.field),
            groups: this.state.groups.filter(g => g.field)
        });
    }

    updateExecutionStats(executionTime) {
        /**
         * Оновлення статистики виконання
         */
        const stats = this.state.executionStats;
        stats.totalExecutions++;
        stats.lastExecutionTime = executionTime;
        stats.avgExecutionTime = (
            (stats.avgExecutionTime * (stats.totalExecutions - 1) + executionTime) /
            stats.totalExecutions
        );
    }

    clearCache() {
        /**
         * Очищення кешу
         */
        this.state.cachedResults.clear();
        this.showInfo(_t("Кеш очищено"));
    }

    // === Автооновлення ===

    toggleAutoRefresh() {
        /**
         * Перемикання автооновлення
         */
        this.state.autoRefresh = !this.state.autoRefresh;

        if (this.state.autoRefresh) {
            this.startAutoRefresh();
            this.showSuccess(_t("Автооновлення увімкнено"));
        } else {
            this.stopAutoRefresh();
            this.showInfo(_t("Автооновлення вимкнено"));
        }
    }

    startAutoRefresh() {
        /**
         * Запуск автооновлення
         */
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
        }

        this.refreshTimer = setInterval(() => {
            if (this.state.reportData) {
                this.executeWithCache();
            }
        }, this.state.refreshInterval);
    }

    stopAutoRefresh() {
        /**
         * Зупинка автооновлення
         */
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }

    setRefreshInterval(seconds) {
        /**
         * Встановлення інтервалу оновлення
         */
        this.state.refreshInterval = seconds * 1000;

        if (this.state.autoRefresh) {
            this.startAutoRefresh();
        }

        this.showInfo(_t("Інтервал оновлення: ") + seconds + _t(" секунд"));
    }

    // === Історія дій ===

    addToHistory(action, data = {}) {
        /**
         * Додавання дії до історії
         */
        const historyItem = {
            action,
            data,
            timestamp: Date.now(),
            state: JSON.parse(JSON.stringify({
                selectedFields: this.state.selectedFields,
                filters: this.state.filters,
                groups: this.state.groups,
                sorts: this.state.sorts
            }))
        };

        // Обрізаємо історію якщо потрібно
        if (this.state.historyIndex < this.state.history.length - 1) {
            this.state.history = this.state.history.slice(0, this.state.historyIndex + 1);
        }

        this.state.history.push(historyItem);
        this.state.historyIndex = this.state.history.length - 1;

        // Обмежуємо розмір історії
        if (this.state.history.length > 50) {
            this.state.history.shift();
            this.state.historyIndex--;
        }
    }

    undo() {
        /**
         * Скасування останньої дії
         */
        if (this.state.historyIndex > 0) {
            this.state.historyIndex--;
            const previousState = this.state.history[this.state.historyIndex].state;
            this.restoreState(previousState);
            this.showInfo(_t("Дію скасовано"));
        } else {
            this.showWarning(_t("Немає дій для скасування"));
        }
    }

    redo() {
        /**
         * Повторення скасованої дії
         */
        if (this.state.historyIndex < this.state.history.length - 1) {
            this.state.historyIndex++;
            const nextState = this.state.history[this.state.historyIndex].state;
            this.restoreState(nextState);
            this.showInfo(_t("Дію повторено"));
        } else {
            this.showWarning(_t("Немає дій для повторення"));
        }
    }

    restoreState(savedState) {
        /**
         * Відновлення стану зі збереженого
         */
        Object.assign(this.state, savedState);
    }

    // === Експорт/Імпорт налаштувань ===

    async exportSettings() {
        /**
         * Експорт налаштувань звіту в JSON
         */
        const settings = {
            model: this.state.selectedModel,
            fields: this.state.selectedFields,
            filters: this.state.filters,
            groups: this.state.groups,
            sorts: this.state.sorts,
            metadata: {
                exported_at: new Date().toISOString(),
                version: "1.0"
            }
        };

        const blob = new Blob([JSON.stringify(settings, null, 2)], {
            type: 'application/json'
        });

        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `report_settings_${Date.now()}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        this.showSuccess(_t("Налаштування експортовано"));
    }

    async importSettings() {
        /**
         * Імпорт налаштувань звіту з JSON
         */
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';

        input.onchange = async (event) => {
            const file = event.target.files[0];
            if (!file) return;

            try {
                const text = await file.text();
                const settings = JSON.parse(text);

                // Перевіряємо структуру
                if (!settings.model || !settings.fields) {
                    throw new Error(_t("Неправильний формат файлу налаштувань"));
                }

                // Застосовуємо налаштування
                if (settings.model) {
                    await this.onModelChange(settings.model.id);
                }

                this.state.selectedFields = settings.fields || [];
                this.state.filters = settings.filters || [];
                this.state.groups = settings.groups || [];
                this.state.sorts = settings.sorts || [];

                this.addToHistory('import_settings', { filename: file.name });
                this.showSuccess(_t("Налаштування імпортовано"));

            } catch (error) {
                this.showError(_t("Помилка імпорту налаштувань"), error);
            }
        };

        input.click();
    }

    // === Очищення при знищенні компонента ===

    willDestroy() {
        super.willDestroy && super.willDestroy();
        this.stopAutoRefresh();
    }
}

/**
 * Діалог масового вибору полів
 */
class BulkFieldSelectionDialog extends Component {
    setup() {
        this.state = useState({
            selectedFields: [],
            searchTerm: '',
            selectAll: false
        });
    }

    get filteredFields() {
        const term = this.state.searchTerm.toLowerCase();
        return this.props.availableFields.filter(field =>
            field.string.toLowerCase().includes(term) ||
            field.name.toLowerCase().includes(term)
        );
    }

    toggleField(field) {
        const index = this.state.selectedFields.findIndex(f => f.name === field.name);
        if (index >= 0) {
            this.state.selectedFields.splice(index, 1);
        } else {
            this.state.selectedFields.push(field);
        }
    }

    toggleSelectAll() {
        if (this.state.selectAll) {
            this.state.selectedFields = [];
        } else {
            this.state.selectedFields = [...this.filteredFields];
        }
        this.state.selectAll = !this.state.selectAll;
    }

    confirm() {
        this.props.onConfirm(this.state.selectedFields);
        this.props.close();
    }
}

BulkFieldSelectionDialog.template = "universal_reports.BulkFieldSelectionDialog";
BulkFieldSelectionDialog.components = { Dialog };

/**
 * Діалог рекомендацій полів
 */
class FieldRecommendationDialog extends Component {
    setup() {
        this.state = useState({
            acceptedFields: [...this.props.recommendations]
        });
    }

    toggleField(field) {
        const index = this.state.acceptedFields.findIndex(f => f.name === field.name);
        if (index >= 0) {
            this.state.acceptedFields.splice(index, 1);
        } else {
            this.state.acceptedFields.push(field);
        }
    }

    acceptRecommendations() {
        this.props.onAccept(this.state.acceptedFields);
        this.props.close();
    }
}

FieldRecommendationDialog.template = "universal_reports.FieldRecommendationDialog";
FieldRecommendationDialog.components = { Dialog };

// Реєстрація розширеного компонента
registry.category("actions").add("universal_reports.report_builder_extended_action", ReportBuilderExtended);