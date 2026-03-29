from config import DISCLAIMER_TEXT
from classes.webui.i18n.const_de import TRANSLATIONS as DE_TRANSLATIONS
from classes.webui.i18n.const_en import TRANSLATIONS as EN_TRANSLATIONS
from classes.webui.i18n.const_es import TRANSLATIONS as ES_TRANSLATIONS
from classes.webui.i18n.const_fr import TRANSLATIONS as FR_TRANSLATIONS
from classes.webui.i18n.const_pl import TRANSLATIONS as PL_TRANSLATIONS
from classes.webui.i18n.const_ua import TRANSLATIONS as UA_TRANSLATIONS

LANGUAGE_OPTIONS = (
    ("en", "🇬🇧 English"),
    ("de", "🇩🇪 Deutsch"),
    ("es", "🇪🇸 Español"),
    ("pl", "🇵🇱 Polski"),
    ("uk", "🇺🇦 Українська"),
    ("fr", "🇫🇷 Français"),
)

TRANSLATIONS = {
    "en": {**EN_TRANSLATIONS, "disclaimer": DISCLAIMER_TEXT},
    "de": {**DE_TRANSLATIONS, "disclaimer": DISCLAIMER_TEXT},
    "es": {**ES_TRANSLATIONS, "disclaimer": DISCLAIMER_TEXT},
    "pl": {**PL_TRANSLATIONS, "disclaimer": DISCLAIMER_TEXT},
    "uk": {**UA_TRANSLATIONS, "disclaimer": DISCLAIMER_TEXT},
    "fr": {**FR_TRANSLATIONS, "disclaimer": DISCLAIMER_TEXT},
}
