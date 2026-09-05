<template>
    <v-text-field
        :value="text"
        :label="label"
        type="text"
        inputmode="numeric"
        maxlength="5"
        placeholder="HH:MM"
        @focus="onFocus"
        @blur="onBlur"
        @input="onInput"
    ></v-text-field>
</template>

<script>
// 24 小时制时间输入框：v-model 绑定 "HH:MM" 字符串。
// 原生 input[type=time] 的 12/24 小时制受系统区域设置控制、无法强制，
// 因此用普通文本框 + 输入掩码：键入数字自动格式化为 HH:MM，
// 小时限制 00-23、分钟限制 00-59，失焦时规范化补全。
export default {
    name: "AppTimePicker",
    props: {
        value: { type: String, default: "00:00" },
        label: { type: String, default: "" },
    },
    data() {
        return {
            text: this.value,
            focused: false,
        };
    },
    watch: {
        value(v) {
            // 聚焦输入时不打断用户键入；外部（如联动计算/数据回填）变更时同步显示
            if (!this.focused) this.text = v;
        },
    },
    methods: {
        onFocus() {
            this.focused = true;
        },
        onInput(val) {
            const digits = val.replace(/\D/g, "").slice(0, 4);
            let display = digits;
            if (digits.length >= 3) {
                // 3 位数字且前两位不是合法小时（如输入 830 表示 8:30），按 1 位小时处理
                if (digits.length === 3 && parseInt(digits.slice(0, 2), 10) > 23) {
                    display = digits[0] + ":" + digits.slice(1);
                } else {
                    display = digits.slice(0, 2) + ":" + digits.slice(2);
                }
            }
            this.text = display;
            // 仅在能解析出完整合法时间时才同步给父级，避免 "8" 这类半成品污染联动计算
            if (display.includes(":")) {
                const parsed = this.parse(display);
                if (parsed) this.$emit("input", parsed);
            }
        },
        onBlur() {
            this.focused = false;
            const parsed = this.parse(this.text) || this.value;
            this.text = parsed;
            this.$emit("input", parsed);
            this.$emit("change", parsed);
        },
        // 兼容 "HH:MM"、"H:MM"、"HHMM"、"HMM" 等写法，合法则返回规范化的 "HH:MM"，否则 null
        parse(s) {
            if (!s) return null;
            let h;
            let m;
            if (s.includes(":")) {
                const parts = s.split(":");
                h = parseInt(parts[0], 10);
                m = parseInt(parts[1] || "0", 10);
            } else {
                const d = s.replace(/\D/g, "");
                if (d.length <= 2) {
                    h = parseInt(d, 10);
                    m = 0;
                } else if (d.length === 3) {
                    h = parseInt(d[0], 10);
                    m = parseInt(d.slice(1), 10);
                } else {
                    h = parseInt(d.slice(0, 2), 10);
                    m = parseInt(d.slice(2), 10);
                }
            }
            if (isNaN(h) || isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59) return null;
            return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
        },
    },
};
</script>
