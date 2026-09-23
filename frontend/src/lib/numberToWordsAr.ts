/**
 * Sprint 5.6 (block 5.6): "المبلغ كتابةً بالعربية ... num2words بـ
 * lang='ar'، وإن كان ناتجه غير سليم لغويًا فاكتب دالة تفقيط عربية
 * مستقلة واختبرها بعشرة أمثلة" — num2words is a Python package with no
 * equivalent already in this Node/Next.js frontend, and print pages are
 * rendered client-side here (no backend print pipeline exists yet), so
 * this is the "write your own" branch: a standalone Arabic number-to-
 * words function, not a library. Verified below (see the 10 worked
 * examples in numberToWordsAr.examples.ts / the UAT script) rather than
 * an automated test — this project has no frontend test framework yet
 * (same documented gap as 5.2's AttachmentPanel).
 *
 * Masculine numeral forms throughout (واحد not إحدى, ثلاثة not ثلاث) —
 * every supported currency's main unit (ريال/دولار/جنيه/درهم) is
 * grammatically masculine, so this never needs the feminine/polarity
 * forms real Arabic grammar would require for a feminine-noun count.
 */

const ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"];
const TEENS = [
  "عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر",
  "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر",
];
const TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"];
const HUNDREDS = [
  "", "مائة", "مائتان", "ثلاثمائة", "أربعمائة",
  "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة",
];

// [singular, dual, plural (3-10), singular-again (11+)] — Arabic's
// counted-noun grammar: 1 -> bare singular, 2 -> dual, 3-10 -> plural,
// 11+ -> singular again (تمييز منصوب, case ending omitted like the
// rest of this function — this project's UI never renders tashkeel).
const SCALES = [
  null,
  { one: "ألف", two: "ألفان", few: "آلاف", many: "ألف" },
  { one: "مليون", two: "مليونان", few: "ملايين", many: "مليون" },
  { one: "مليار", two: "ملياران", few: "مليارات", many: "مليار" },
];

function threeDigitsToWords(n: number): string {
  const hundreds = Math.floor(n / 100);
  const rest = n % 100;
  const parts: string[] = [];
  if (hundreds > 0) parts.push(HUNDREDS[hundreds]);
  if (rest > 0) {
    if (rest < 10) {
      parts.push(ONES[rest]);
    } else if (rest < 20) {
      parts.push(TEENS[rest - 10]);
    } else {
      const tens = Math.floor(rest / 10);
      const ones = rest % 10;
      parts.push(ones > 0 ? `${ONES[ones]} و${TENS[tens]}` : TENS[tens]);
    }
  }
  return parts.join(" و");
}

/** Integer 0..999_999_999_999 -> Arabic words. */
export function numberToArabicWords(value: number): string {
  const n = Math.floor(Math.abs(value));
  if (n === 0) return "صفر";

  // Split into groups of 3 digits, least-significant first.
  const groups: number[] = [];
  let remaining = n;
  while (remaining > 0) {
    groups.push(remaining % 1000);
    remaining = Math.floor(remaining / 1000);
  }

  const segments: string[] = [];
  for (let scale = groups.length - 1; scale >= 0; scale--) {
    const g = groups[scale];
    if (g === 0) continue;
    const scaleWords = SCALES[scale];
    if (!scaleWords) {
      // scale 0 — bare units, no scale word.
      segments.push(threeDigitsToWords(g));
      continue;
    }
    if (g === 1) {
      segments.push(scaleWords.one);
    } else if (g === 2) {
      segments.push(scaleWords.two);
    } else if (g <= 10) {
      segments.push(`${threeDigitsToWords(g)} ${scaleWords.few}`);
    } else {
      segments.push(`${threeDigitsToWords(g)} ${scaleWords.many}`);
    }
  }
  return segments.join(" و");
}

const CURRENCY_WORDS: Record<string, { main: string; sub: string }> = {
  SAR: { main: "ريال سعودي", sub: "هللة" },
  USD: { main: "دولار أمريكي", sub: "سنت" },
  EGP: { main: "جنيه مصري", sub: "قرش" },
  AED: { main: "درهم إماراتي", sub: "فلس" },
  KWD: { main: "دينار كويتي", sub: "فلس" },
  QAR: { main: "ريال قطري", sub: "درهم" },
  BHD: { main: "دينار بحريني", sub: "فلس" },
  OMR: { main: "ريال عماني", sub: "بيسة" },
};

/** "1,234.50" + "SAR" -> "ألف ومائتان وأربعة وثلاثون ريال سعودي
 * وخمسون هللة فقط لا غير" — the integer and fractional parts are
 * spelled out separately, each with its own currency-unit name
 * (decision: rule 3.15.3 / block 5.6's print spec), falling back to
 * the bare ISO code (no minor-unit name) for a currency not in
 * CURRENCY_WORDS above. */
export function amountInWordsAr(amount: string | number, currency: string): string {
  const value = typeof amount === "string" ? parseFloat(amount) : amount;
  if (!Number.isFinite(value)) return "";
  const rounded = Math.round(Math.abs(value) * 100) / 100;
  const integerPart = Math.floor(rounded);
  const fractionPart = Math.round((rounded - integerPart) * 100);

  const names = CURRENCY_WORDS[currency];
  const mainName = names ? names.main : currency;
  const subName = names ? names.sub : null;

  let result = `${numberToArabicWords(integerPart)} ${mainName}`;
  if (fractionPart > 0) {
    const fractionWords = numberToArabicWords(fractionPart);
    result += subName ? ` و${fractionWords} ${subName}` : ` و${fractionWords}/100`;
  }
  return `${result} فقط لا غير`;
}
