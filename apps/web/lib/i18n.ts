export type SupportedLocale = "en" | "ar";

export const DEFAULT_LOCALE: SupportedLocale =
  process.env.NEXT_PUBLIC_LOCALE === "ar" ? "ar" : "en";

export const UI_MESSAGES = {
  en: {
    "nav.forecast": "Forecast",
    "nav.map": "Map room",
    "nav.model": "Model lab",
    "nav.calendar": "Calendar",
    "nav.methodology": "Methodology",
    "status.apiLive": "API LIVE",
    "status.sample": "SAMPLE SNAPSHOT",
    "status.connecting": "CONNECTING",
    "forecast.winProbability": "WIN PROBABILITY",
    "forecast.pathway": "PATHWAY TO MAJORITY",
    "forecast.drivers": "MODEL DRIVER MATRIX",
    "forecast.history": "IMMUTABLE FORECAST HISTORY",
    "forecast.sources": "SOURCE LEDGER",
    "forecast.coalition": "COALITION SIMULATOR",
    "forecast.unavailable": "Forecast unavailable"
  },
  ar: {
    "nav.forecast": "التوقعات",
    "nav.map": "غرفة الخرائط",
    "nav.model": "مختبر النماذج",
    "nav.calendar": "التقويم",
    "nav.methodology": "المنهجية",
    "status.apiLive": "البيانات مباشرة",
    "status.sample": "لقطة تجريبية",
    "status.connecting": "جارٍ الاتصال",
    "forecast.winProbability": "احتمال الفوز",
    "forecast.pathway": "طريق الأغلبية",
    "forecast.drivers": "مصفوفة عوامل النموذج",
    "forecast.history": "سجل التوقعات غير القابل للتغيير",
    "forecast.sources": "سجل المصادر",
    "forecast.coalition": "محاكي الائتلاف",
    "forecast.unavailable": "التوقع غير متاح"
  }
} as const;

export type MessageKey = keyof typeof UI_MESSAGES.en;

export function message(key: MessageKey): string {
  return UI_MESSAGES[DEFAULT_LOCALE][key];
}

export function directionForLocale(locale: string): "ltr" | "rtl" {
  return ["ar", "fa", "he", "ur"].includes(locale.split("-")[0].toLowerCase()) ? "rtl" : "ltr";
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat(DEFAULT_LOCALE).format(value);
}

export function formatDate(value: string | number | Date, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(DEFAULT_LOCALE, { timeZone: "UTC", ...options }).format(new Date(value));
}

export function formatDateTime(value: string | number | Date): string {
  return formatDate(value, { dateStyle: "medium", timeStyle: "short" });
}
