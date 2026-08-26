/** What the elder screen says, in the language their family chose for them.
 *
 *  Only the languages that are actually translated appear in LANGUAGE_CHOICES.
 *  Adding one is a data-only edit: fill in the column and list it there. A
 *  half-translated language is worse than an untranslated one, because the
 *  gaps land on the screen as English mid-sentence.
 *
 *  Medicine names, doses and caregiver notes are never translated. They are
 *  what the caregiver typed, and a drug name that has been through a
 *  translator is the one mistake this app exists to prevent.
 */

export type Language = "en" | "te";

export const LANGUAGE_CHOICES: { code: Language; label: string }[] = [
  // Each in its own language, because the person picking it may not read the
  // other one.
  { code: "en", label: "English" },
  { code: "te", label: "తెలుగు" },
];

type Entry = Record<Language, string>;

const STRINGS = {
  oneMoment: {
    en: "One moment…",
    te: "ఒక్క నిమిషం…",
  },
  cannotReach: {
    en: "Cannot reach CareBridge",
    te: "CareBridge అందుబాటులో లేదు",
  },
  checkInternet: {
    en: "Please check the internet connection.",
    te: "ఇంటర్నెట్ కనెక్షన్ చూడండి.",
  },
  checkInternetRetry: {
    en: "Please check the internet connection, then try again.",
    te: "ఇంటర్నెట్ కనెక్షన్ చూసి, మళ్ళీ ప్రయత్నించండి.",
  },
  tryAgain: {
    en: "Try again",
    te: "మళ్ళీ ప్రయత్నించండి",
  },
  notSetUp: {
    en: "This phone is not set up yet",
    te: "ఈ ఫోన్ ఇంకా సిద్ధం కాలేదు",
  },
  askFamilyToSetUp: {
    en: "Ask your family to set it up from CareBridge.",
    te: "CareBridge నుండి సిద్ధం చేయమని మీ కుటుంబాన్ని అడగండి.",
  },
  nothingToTake: {
    en: "Nothing to take right now",
    te: "ఇప్పుడు తీసుకోవలసినది ఏమీ లేదు",
  },
  willLetYouKnow: {
    en: "CareBridge will let you know when it is time.",
    te: "సమయం అయినప్పుడు CareBridge మీకు తెలియజేస్తుంది.",
  },
  keepPageOpen: {
    en: "Keep this page open and CareBridge will show you when it is time.",
    te: "ఈ పేజీని తెరిచి ఉంచండి, సమయం అయినప్పుడు CareBridge చూపిస్తుంది.",
  },
  letPhoneRing: {
    en: "Let this phone ring for medicines",
    te: "మందుల కోసం ఈ ఫోన్ మోగనివ్వండి",
  },
  notificationsBlocked: {
    en: "This phone is set to block notifications. Reminders still appear on this page while it is open.",
    te: "ఈ ఫోన్‌లో నోటిఫికేషన్లు నిలిపివేయబడ్డాయి. ఈ పేజీ తెరిచి ఉన్నంత వరకు గుర్తులు ఇక్కడే కనిపిస్తాయి.",
  },
  medicineTime: {
    en: "Medicine time",
    te: "మందు వేసుకునే సమయం",
  },
  iTookIt: {
    en: "I took it",
    te: "తీసుకున్నాను",
  },
  remindMeLater: {
    en: "Remind me later",
    te: "తర్వాత గుర్తు చేయండి",
  },
  speakToCareBridge: {
    en: "Speak to CareBridge",
    te: "CareBridge తో మాట్లాడండి",
  },
  listening: {
    en: "Listening…",
    te: "వింటున్నాను…",
  },
  recordedThanks: {
    en: "Thank you. I have recorded it.",
    te: "ధన్యవాదాలు. నమోదు చేశాను.",
  },
  willRemindInTen: {
    en: "Alright, I will remind you again in ten minutes.",
    te: "సరే, పది నిమిషాల్లో మళ్ళీ గుర్తు చేస్తాను.",
  },
  didNotGoThrough: {
    en: "That did not go through. Please try again.",
    te: "అది పూర్తి కాలేదు. మళ్ళీ ప్రయత్నించండి.",
  },
  offlineAnswer: {
    en: "CareBridge is offline. Your answer may not be saved yet.",
    te: "CareBridge ఆఫ్‌లైన్‌లో ఉంది. మీ సమాధానం ఇంకా భద్రపరచబడకపోవచ్చు.",
  },
  somethingWrong: {
    en: "Something went wrong. Please use the buttons below.",
    te: "ఏదో పొరపాటు జరిగింది. కింది బటన్లను వాడండి.",
  },
  tapToHear: {
    en: "Tap anywhere to hear the message from your family.",
    te: "మీ కుటుంబం పంపిన సందేశం వినడానికి ఎక్కడైనా తాకండి.",
  },
  micBlocked: {
    en: "Microphone access is blocked.",
    te: "మైక్రోఫోన్ అనుమతి నిలిపివేయబడింది.",
  },
  didNotCatch: {
    en: "I did not catch that.",
    te: "నాకు అర్థం కాలేదు.",
  },
  cannotListen: {
    en: "This browser cannot listen. Please use the buttons.",
    te: "ఈ బ్రౌజర్ వినలేదు. బటన్లను వాడండి.",
  },
} satisfies Record<string, Entry>;

/** Word order differs, so these are whole sentences with a slot, never
 *  concatenation. English puts the food instruction last and Telugu puts it
 *  first; "Take it" + food would be wrong in one of them. */
const TEMPLATES = {
  takeIt: {
    en: "Take it {food}",
    te: "{food} తీసుకోండి",
  },
  moreAfterThis: {
    en: "{count} more after this one",
    te: "దీని తర్వాత మరో {count}",
  },
} satisfies Record<string, Entry>;

const FOOD = {
  BEFORE_FOOD: { en: "before food", te: "భోజనానికి ముందు" },
  AFTER_FOOD: { en: "after food", te: "భోజనం తర్వాత" },
  WITH_FOOD: { en: "with food", te: "భోజనంతో పాటు" },
  ANY_TIME: { en: "at any time", te: "ఏ సమయంలోనైనా" },
} satisfies Record<string, Entry>;

const FALLBACK: Language = "en";

/** An elder recorded with a language nobody has translated yet still gets a
 *  working screen, in English, rather than a blank one. */
function pick(entry: Entry, language: string): string {
  return entry[language as Language] ?? entry[FALLBACK];
}

export type StringKey = keyof typeof STRINGS;

export function t(key: StringKey, language: string): string {
  return pick(STRINGS[key], language);
}

export function tFood(foodInstruction: string, language: string): string {
  const entry = FOOD[foodInstruction as keyof typeof FOOD];
  return entry ? pick(entry, language) : pick(FOOD.ANY_TIME, language);
}

export function tTemplate(
  key: keyof typeof TEMPLATES,
  language: string,
  slots: Record<string, string | number>,
): string {
  return Object.entries(slots).reduce(
    (text, [name, value]) => text.replace(`{${name}}`, String(value)),
    pick(TEMPLATES[key], language),
  );
}
