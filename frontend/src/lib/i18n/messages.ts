/**
 * Message catalogs.
 *
 * Every sentence is a whole template with its parameters interpolated. None is
 * assembled from fragments: word order differs between languages, and a
 * sentence built by concatenation is correct in the language it was written in
 * and wrong everywhere else.
 */

export type Locale = "ru" | "en";

export interface Catalog {
  validation: Record<string, string>;
  slot: Record<string, string>;
  template: Record<string, string>;
  section: Record<string, string>;
  ui: Record<string, string>;
}

/**
 * Validation keys, from `ration.domain.validation`. The completeness test
 * compares this list against the codes the backend can emit, so a new code
 * without a translation fails the build rather than rendering a raw key.
 */
const ru: Catalog = {
  validation: {
    "validation.day_kcal_out_of_range":
      "День {day}: {actual} ккал, нужно {min}–{max}",
    "validation.day_protein_below_min":
      "День {day}: {actual} г белка, минимум {min}",
    "validation.slot_kcal_out_of_budget":
      "{slot}, день {day}: {actual} ккал, бюджет {min}–{max}",
    "validation.slot_protein_out_of_budget":
      "{slot}, день {day}: {actual} г белка, нужно от {min}",
    "validation.excluded_ingredient":
      "{slot}, день {day}: «{ingredient}» исключён из рациона",
    "validation.caution_threshold_exceeded":
      "День {day}: «{ingredient}» {actual} г, порог {threshold} г",
    "validation.frequency_exceeded":
      "«{tag}» встречается {actual} раз за неделю, допустимо {max}",
    "validation.template_gate_violated":
      "День {day}: «{tag}» не допускается в режиме «{template}»",
    "validation.batch_not_consecutive":
      "«{module}» готовится впрок, но стоит на днях {days} — не подряд",
    "validation.multiple_main_entries":
      "{slot}, день {day}: {actual} основных блюда, нужно одно",
    "validation.slot_empty": "{slot}, день {day}: пусто",
    "validation.day_unplanned": "День {day}: не запланирован",
  },
  slot: {
    breakfast: "Завтрак",
    lunch: "Обед",
    snack: "Перекус",
    dinner: "Ужин",
    treat: "Дополнение",
  },
  template: {
    normal: "Обычный день",
    long_shift: "Длинная смена",
    training: "Тренировка",
    duty_24h: "Суточное дежурство",
  },
  section: {
    meat_fish: "Мясо, рыба и морепродукты",
    dairy: "Молочные продукты и яйца",
    produce: "Овощи и зелень",
    fruit: "Фрукты и ягоды",
    grains: "Крупы, лапша и хлеб",
    nuts_pastes: "Орехи, пасты и добавки",
    oils_sauces: "Масло, соусы и приправы",
    supplements: "Добавки",
    treats: "Сладкое и вино",
    other: "Прочее",
  },
  ui: {
    "today.title": "Сегодня",
    "today.nothing_planned": "На этот день ничего не запланировано",
    "today.outside_plan": "Этот день вне плана.",
    "today.plan_week": "Неделя плана",
    "today.go_to_plan": "Перейти к плану",
    "today.home_only": "Дома",
    "today.day_total": "Итого за день: {kcal} ккал · {protein} г",
    "today.slot_kcal": "{kcal} ккал",
    "today.entry_line": "{grams} г · {kcal} ккал · {protein} г белка",
    "today.yesterday": "Вчера",
    "today.tomorrow": "Завтра",
    "shopping.title": "Список покупок",
    "shopping.staples": "Запасы — проверить, не кончились ли",
    "shopping.progress": "{done} из {total}",
    "shopping.critical": "Важен размер",
    "shopping.amount_g": "{amount} г",
    "shopping.amount_pcs": "{count} шт",
    "rate.liked": "Понравилось",
    "rate.neutral": "Нормально",
    "rate.disliked": "Не понравилось",
    "validation.clean": "Нарушений нет",
    "validation.errors": "Ошибок: {count}",
    "validation.warnings": "Предупреждений: {count}",
    "common.loading": "Загрузка…",
    "common.error": "Что-то пошло не так",
    "common.retry": "Попробовать снова",
    "auth.email": "Почта",
    "auth.password": "Пароль",
    "auth.failed": "Почта или пароль неверны",
    "auth.submit": "Войти",
  },
};

const en: Catalog = {
  validation: {
    "validation.day_kcal_out_of_range":
      "Day {day}: {actual} kcal, target {min}–{max}",
    "validation.day_protein_below_min":
      "Day {day}: {actual} g protein, minimum {min}",
    "validation.slot_kcal_out_of_budget":
      "{slot}, day {day}: {actual} kcal, budget {min}–{max}",
    "validation.slot_protein_out_of_budget":
      "{slot}, day {day}: {actual} g protein, floor {min}",
    "validation.excluded_ingredient":
      "{slot}, day {day}: “{ingredient}” is excluded",
    "validation.caution_threshold_exceeded":
      "Day {day}: “{ingredient}” {actual} g, threshold {threshold} g",
    "validation.frequency_exceeded":
      "“{tag}” appears {actual} times this week, limit {max}",
    "validation.template_gate_violated":
      "Day {day}: “{tag}” is not allowed on a {template} day",
    "validation.batch_not_consecutive":
      "“{module}” is cooked ahead but planned on days {days}, which are not consecutive",
    "validation.multiple_main_entries":
      "{slot}, day {day}: {actual} main dishes, expected one",
    "validation.slot_empty": "{slot}, day {day}: empty",
    "validation.day_unplanned": "Day {day}: unplanned",
  },
  slot: {
    breakfast: "Breakfast",
    lunch: "Lunch",
    snack: "Snack",
    dinner: "Dinner",
    treat: "Treat",
  },
  template: {
    normal: "Normal day",
    long_shift: "Long shift",
    training: "Training",
    duty_24h: "24-hour duty",
  },
  section: {
    meat_fish: "Meat, fish and seafood",
    dairy: "Dairy and eggs",
    produce: "Vegetables and greens",
    fruit: "Fruit and berries",
    grains: "Grains, noodles and bread",
    nuts_pastes: "Nuts, pastes and extras",
    oils_sauces: "Oils, sauces and seasoning",
    supplements: "Supplements",
    treats: "Sweets and wine",
    other: "Other",
  },
  ui: {
    "today.title": "Today",
    "today.nothing_planned": "Nothing planned for this day",
    "today.outside_plan": "This day is outside the plan.",
    "today.plan_week": "The plan's week",
    "today.go_to_plan": "Go to the plan",
    "today.home_only": "At home",
    "today.day_total": "Day total: {kcal} kcal · {protein} g",
    "today.slot_kcal": "{kcal} kcal",
    "today.entry_line": "{grams} g · {kcal} kcal · {protein} g protein",
    "today.yesterday": "Yesterday",
    "today.tomorrow": "Tomorrow",
    "shopping.title": "Shopping list",
    "shopping.staples": "Staples — check if low",
    "shopping.progress": "{done} of {total}",
    "shopping.critical": "Size matters",
    "shopping.amount_g": "{amount} g",
    "shopping.amount_pcs": "{count} pcs",
    "rate.liked": "Liked",
    "rate.neutral": "Neutral",
    "rate.disliked": "Disliked",
    "validation.clean": "No findings",
    "validation.errors": "Errors: {count}",
    "validation.warnings": "Warnings: {count}",
    "common.loading": "Loading…",
    "common.error": "Something went wrong",
    "common.retry": "Try again",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.failed": "Wrong email or password",
    "auth.submit": "Sign in",
  },
};

export const CATALOGS: Record<Locale, Catalog> = { ru, en };
