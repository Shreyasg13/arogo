"""
i18n_server.py — Server-side message catalog for Arogo.

The client UI localizes itself from static/js/app.js (the localStorage 'arogo_lang'
toggle). But emails and Web Push notifications are composed by the Flask app and the
headless scheduler worker — no browser, no localStorage — so they need their own
catalog keyed by the recipient's stored language (user_profile.language).

Usage:
    from i18n_server import tr
    tr(lang, 'push.dose_title', med='Metformin')   # lang is 'en' | 'hi'

`tr` never raises: an unknown key returns the key; a missing translation falls back
to English; a bad .format() returns the unformatted template. English strings are
kept byte-for-byte identical to what the code sent before this catalog existed, so
default-language (en) output — and the tests that assert on it — are unchanged.
"""
from __future__ import annotations

# key -> {'en': template, 'hi': template}. Templates use str.format named fields.
MESSAGES: dict[str, dict[str, str]] = {
    # ── Push: dose reminders ──────────────────────────────────────────────
    'push.dose_title':      {'en': '💊 Time for {med}',        'hi': '💊 {med} का समय'},
    'push.dose_when_early': {'en': 'Due at {time} · in ~{min} min', 'hi': '{time} पर देय · ~{min} मिनट में'},
    'push.dose_when_sched': {'en': 'Scheduled at {time}',      'hi': '{time} पर निर्धारित'},
    'push.dose_for':        {'en': ' · for {purpose}',         'hi': ' · {purpose} के लिए'},
    'push.dose_with_food':  {'en': ' · take with food',        'hi': ' · भोजन के साथ लें'},
    'push.act_taken':       {'en': '✓ Taken',                  'hi': '✓ लिया'},
    'push.act_later':       {'en': 'Later',                    'hi': 'बाद में'},
    'push.snooze_title':    {'en': '💊 Still due: {med}',      'hi': '💊 अब भी देय: {med}'},
    'push.snooze_body':     {'en': 'Snoozed reminder — take it when you can.',
                             'hi': 'टाला गया रिमाइंडर — जब हो सके तब लें।'},

    # ── Push: water ───────────────────────────────────────────────────────
    'push.water_title': {'en': '💧 Hydration check', 'hi': '💧 पानी की जाँच'},
    'push.water_body':  {'en': "You're behind on water — about {ml}ml to go today.",
                         'hi': 'आप पानी में पीछे हैं — आज लगभग {ml}ml बाकी।'},
    'push.water_act':   {'en': '💧 {ml}ml', 'hi': '💧 {ml}ml'},

    # ── Push: evening habit / sleep / mood ────────────────────────────────
    'push.habit_title': {'en': '⭐ Evening habit check', 'hi': '⭐ शाम की आदत जाँच'},
    'push.habit_body':  {'en': 'Tick off what you completed today.', 'hi': 'आज जो पूरा किया उसे टिक करें।'},
    'push.sleep_title': {'en': '🌙 Wind-down time', 'hi': '🌙 आराम का समय'},
    'push.sleep_body':  {'en': "Log last night's sleep and get ready for bed.",
                         'hi': 'बीती रात की नींद दर्ज करें और सोने की तैयारी करें।'},
    'push.mood_title':  {'en': '😊 How was your day?', 'hi': '😊 आपका दिन कैसा रहा?'},
    'push.mood_body':   {'en': 'A one-line journal entry keeps the streak alive.',
                         'hi': 'एक पंक्ति की डायरी स्ट्रीक बनाए रखती है।'},
    'push.mood_good':     {'en': '😊 Good',      'hi': '😊 अच्छा'},
    'push.mood_notgreat': {'en': '😕 Not great', 'hi': '😕 अच्छा नहीं'},

    # ── Push: measurement check-ins ───────────────────────────────────────
    'push.meas_bp_title':   {'en': '🩺 Check your blood pressure', 'hi': '🩺 अपना रक्तचाप जाँचें'},
    'push.meas_bp_body':    {'en': 'Take a reading and log it in Arogo.', 'hi': 'एक रीडिंग लें और Arogo में दर्ज करें।'},
    'push.meas_sugar_title':{'en': '🩸 Check your blood sugar', 'hi': '🩸 अपना रक्त शर्करा जाँचें'},
    'push.meas_sugar_body': {'en': 'Time for your sugar reading.', 'hi': 'आपकी शुगर रीडिंग का समय।'},
    'push.meas_weight_title':{'en': '⚖️ Time to weigh in', 'hi': '⚖️ वज़न लेने का समय'},
    'push.meas_weight_body':{'en': 'Step on the scale and log your weight.', 'hi': 'तराज़ू पर खड़े हों और अपना वज़न दर्ज करें।'},
    'push.meas_spo2_title': {'en': '💨 Check your oxygen (SpO2)', 'hi': '💨 अपना ऑक्सीजन (SpO2) जाँचें'},
    'push.meas_spo2_body':  {'en': 'Take a reading and log it.', 'hi': 'एक रीडिंग लें और दर्ज करें।'},
    'push.meas_temp_title': {'en': '🌡️ Check your temperature', 'hi': '🌡️ अपना तापमान जाँचें'},
    'push.meas_temp_body':  {'en': 'Take a reading and log it.', 'hi': 'एक रीडिंग लें और दर्ज करें।'},
    'push.meas_hr_title':   {'en': '💓 Check your heart rate', 'hi': '💓 अपनी हृदय गति जाँचें'},
    'push.meas_hr_body':    {'en': 'Take a reading and log it.', 'hi': 'एक रीडिंग लें और दर्ज करें।'},
    'push.meas_generic_title':{'en': '🩺 Health check-in', 'hi': '🩺 स्वास्थ्य जाँच'},
    'push.meas_generic_body':{'en': 'Take your reading and log it.', 'hi': 'अपनी रीडिंग लें और दर्ज करें।'},

    # ── Push: refill + appointment ────────────────────────────────────────
    'push.refill_title':  {'en': '🔄 Refill {med}', 'hi': '🔄 {med} रिफिल करें'},
    'push.refill_body':   {'en': 'About {days} day{s} of pills left.', 'hi': 'लगभग {days} दिन की गोलियाँ बाकी।'},
    'push.appt_tomorrow': {'en': 'Tomorrow', 'hi': 'कल'},
    'push.appt_today':    {'en': 'Today',    'hi': 'आज'},
    'push.appt_at':       {'en': ' at {time}', 'hi': ' {time} बजे'},

    # ── Email: verification ───────────────────────────────────────────────
    'email.verify_subject': {'en': 'Verify your Arogo email', 'hi': 'अपना Arogo ईमेल सत्यापित करें'},
    'email.verify_body': {
        'en': ('Welcome to Arogo!\n\n'
               'Confirm your email address by opening this link (valid for 24 hours):\n\n'
               '    {link}\n\n'
               "If you didn't create an Arogo account, you can ignore this email.\n"),
        'hi': ('Arogo में आपका स्वागत है!\n\n'
               'इस लिंक को खोलकर अपना ईमेल पता पुष्टि करें (24 घंटे के लिए मान्य):\n\n'
               '    {link}\n\n'
               'यदि आपने Arogo खाता नहीं बनाया, तो इस ईमेल को अनदेखा करें।\n'),
    },

    # ── Email: password reset ─────────────────────────────────────────────
    'email.reset_subject': {'en': 'Reset your Arogo password', 'hi': 'अपना Arogo पासवर्ड रीसेट करें'},
    'email.reset_body': {
        'en': ('Someone requested a password reset for your Arogo account.\n\n'
               'Open this link to choose a new password (valid for 1 hour):\n\n'
               '    {link}\n\n'
               "If this wasn't you, ignore this email — your password is unchanged.\n"),
        'hi': ('किसी ने आपके Arogo खाते के लिए पासवर्ड रीसेट का अनुरोध किया।\n\n'
               'नया पासवर्ड चुनने के लिए यह लिंक खोलें (1 घंटे के लिए मान्य):\n\n'
               '    {link}\n\n'
               'यदि यह आप नहीं थे, तो इस ईमेल को अनदेखा करें — आपका पासवर्ड अपरिवर्तित है।\n'),
    },

    # ── Email: family invite ──────────────────────────────────────────────
    'email.invite_subject': {'en': '{inviter} invited you to their Arogo family group',
                             'hi': '{inviter} ने आपको अपने Arogo परिवार समूह में आमंत्रित किया'},
    'email.invite_body': {
        'en': ('{inviter} invited you to join the family group "{group}" on Arogo.\n\n'
               'Family members choose exactly which health categories they share —\n'
               'nothing is visible unless you turn it on.\n\n'
               'Open this link to join (valid for 72 hours):\n\n'
               '    {link}\n\n'
               "If you don't want to join, just ignore this email.\n"),
        'hi': ('{inviter} ने आपको Arogo पर परिवार समूह "{group}" में शामिल होने का आमंत्रण दिया।\n\n'
               'परिवार के सदस्य ठीक-ठीक चुनते हैं कि कौन-सी स्वास्थ्य श्रेणियाँ साझा करनी हैं —\n'
               'जब तक आप चालू न करें कुछ भी दिखाई नहीं देता।\n\n'
               'शामिल होने के लिए यह लिंक खोलें (72 घंटे के लिए मान्य):\n\n'
               '    {link}\n\n'
               'यदि आप शामिल नहीं होना चाहते, तो इस ईमेल को अनदेखा करें।\n'),
    },
}


def normalize_lang(lang) -> str:
    """Clamp to a supported language code; anything unknown → 'en'."""
    return 'hi' if lang == 'hi' else 'en'


def tr(lang, key: str, **kw) -> str:
    """Translate `key` into `lang`, substituting {named} fields from kw.

    Never raises: unknown key → the key itself; missing translation → English;
    a .format() error (missing/extra field) → the raw template.
    """
    lang = normalize_lang(lang)
    entry = MESSAGES.get(key)
    if not entry:
        s = key
    else:
        s = entry.get(lang) or entry.get('en') or key
    if not kw:
        return s
    try:
        return s.format(**kw)
    except (KeyError, IndexError, ValueError):
        return s
