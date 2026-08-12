"""
Offline machine translation.

Desirable requirement (HMGCC Q&A Q114): translate/index non-English data
sources, starting with German, French, Japanese and Chinese. Uses Argos
Translate, which performs inference fully offline via bundled CTranslate2
models - no network access is ever made at runtime. Language packages are
installed once, ahead of time, into config.TRANSLATE_MODELS_DIR /
"packages" (config.py points ARGOS_PACKAGES_DIR there by default). For a
dev checkout, run `python scripts/install_translation_packages.py` once
(needs internet only for that one-time download); the offline installer
instead lays down pre-downloaded .argosmodel files at install time (see
installer/windows/installer_src/install.ps1 and
installer/linux/installer_src/install.sh) so the target machine never
needs a connection.

Used by the PROACTIVE bias policy (services/bias.py) to translate a
matching non-English source already present in the corpus, with a
provenance note, per Q16's worked example.
"""

from __future__ import annotations

from typing import Optional

import config  # noqa: F401  (import side-effect: sets ARGOS_PACKAGES_DIR before argostranslate loads)


def available_languages() -> list:
    try:
        from argostranslate import translate
        return [{"code": l.code, "name": l.name} for l in translate.get_installed_languages()]
    except Exception:
        return []


def translate_text(text: str, target_lang: str = "en", source_lang: Optional[str] = None) -> dict:
    """Translate text using an installed offline Argos Translate package.

    Never raises - if no matching offline language package is installed
    (e.g. before the installer's language packs have been laid down), the
    original text is returned with engine="unavailable" so callers can
    degrade gracefully instead of failing the whole request.
    """
    try:
        from argostranslate import translate
        langs = translate.get_installed_languages()
        if not langs:
            return {"translated": text, "source_lang": source_lang or "unknown", "engine": "unavailable"}

        by_code = {l.code: l for l in langs}
        src_code = source_lang
        if not src_code or src_code not in by_code:
            from services.bias import detect_text_language
            src_code = detect_text_language(text).get("language")
        src_code = (src_code or "unknown").split("-")[0]

        if src_code not in by_code or target_lang not in by_code:
            return {"translated": text, "source_lang": src_code, "engine": "unavailable"}
        if src_code == target_lang:
            return {"translated": text, "source_lang": src_code, "engine": "noop"}

        translation = by_code[src_code].get_translation(by_code[target_lang])
        if not translation:
            return {"translated": text, "source_lang": src_code, "engine": "unavailable"}

        return {"translated": translation.translate(text), "source_lang": src_code, "engine": "argos"}
    except Exception as exc:
        return {"translated": text, "source_lang": source_lang or "unknown", "engine": f"error: {exc}"}
