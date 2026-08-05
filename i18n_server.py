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
    'push.appt_in_days':  {'en': 'In {days} days', 'hi': '{days} दिन में'},
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

    # ── Weekly digest: headline / wins / concerns / highlight labels ──────
    'digest.headline_empty':  {'en': 'Nothing logged yet — start tracking and your progress will show up here.',
                               'hi': 'अभी कुछ दर्ज नहीं — ट्रैक करना शुरू करें और आपकी प्रगति यहाँ दिखेगी।'},
    'digest.headline_strong': {'en': "Strong week — you're building good habits 💪",
                               'hi': 'शानदार हफ़्ता — आप अच्छी आदतें बना रहे हैं 💪'},
    'digest.headline_solid':  {'en': 'Solid week overall, with a few areas to improve',
                               'hi': 'कुल मिलाकर ठोस हफ़्ता, कुछ क्षेत्रों में सुधार की गुंजाइश'},
    'digest.headline_mixed':  {'en': 'Mixed week — some wins, some things to work on',
                               'hi': 'मिला-जुला हफ़्ता — कुछ जीत, कुछ पर काम बाकी'},
    'digest.headline_tough':  {'en': 'Tough week — small steps still count. Keep going.',
                               'hi': 'कठिन हफ़्ता — छोटे कदम भी मायने रखते हैं। लगे रहें।'},

    'digest.win_sleep':     {'en': 'Averaged {h}h sleep across {nights} of 7 nights',
                             'hi': '7 में से {nights} रातों में औसतन {h}घं नींद'},
    'digest.win_workouts':  {'en': '{days} workout days this week — great consistency',
                             'hi': 'इस हफ़्ते {days} कसरत दिन — बढ़िया निरंतरता'},
    'digest.win_habits':    {'en': '{pct}% habit completion — nearly perfect week',
                             'hi': '{pct}% आदत पूर्णता — लगभग सटीक हफ़्ता'},
    'digest.win_hydration': {'en': 'Well hydrated — averaged {ml}ml/day',
                             'hi': 'अच्छी हाइड्रेशन — औसतन {ml}ml/दिन'},
    'digest.win_burned':    {'en': '{kcal} kcal burned through exercise',
                             'hi': 'कसरत से {kcal} kcal जलाई'},

    'digest.concern_sleep_low':   {'en': 'Sleep averaged {h}h across {nights} nights — under the 7–9h usually recommended. Early night this week?',
                                   'hi': 'नींद {nights} रातों में औसतन {h}घं रही — सामान्यतः अनुशंसित 7–9घं से कम। इस हफ़्ते जल्दी सोएँ?'},
    'digest.concern_sleep_short': {'en': 'Sleep was a bit short ({h}h avg over {nights} nights). Aim for 7h+ tonight.',
                                   'hi': 'नींद थोड़ी कम रही ({nights} रातों में {h}घं औसत)। आज 7घं+ का लक्ष्य रखें।'},
    'digest.concern_workouts':    {'en': 'Only {days} workout day this week. Try for 3+.',
                                   'hi': 'इस हफ़्ते केवल {days} कसरत दिन। 3+ की कोशिश करें।'},
    'digest.concern_habits':      {'en': 'Habits only {pct}% complete. Consider removing habits that no longer fit.',
                                   'hi': 'आदतें केवल {pct}% पूर्ण। जो आदतें अब फिट नहीं बैठतीं उन्हें हटाने पर विचार करें।'},
    'digest.concern_symptom':     {'en': '{name} appeared {count} time{s} this week. Worth noting if it continues.',
                                   'hi': '{name} इस हफ़्ते {count} बार आया। जारी रहे तो ध्यान देने योग्य।'},
    'digest.concern_hydration':   {'en': 'Hydration was low ({ml}ml avg, goal {goal}ml). Try a water reminder.',
                                   'hi': 'हाइड्रेशन कम रही ({ml}ml औसत, लक्ष्य {goal}ml)। पानी का रिमाइंडर आज़माएँ।'},

    'digest.hl_sleep':    {'en': 'Avg sleep ({nights}/7 nights)', 'hi': 'औसत नींद ({nights}/7 रातें)'},
    'digest.hl_workouts': {'en': 'Workout days', 'hi': 'कसरत दिन'},
    'digest.hl_habits':   {'en': 'Habits', 'hi': 'आदतें'},
    'digest.hl_water':    {'en': 'Avg water', 'hi': 'औसत पानी'},
    'digest.hl_burned':   {'en': 'Cal burned', 'hi': 'कैलोरी जली'},

    # ── Weekly digest email scaffolding ───────────────────────────────────
    'email.digest_subject':  {'en': 'Your Arogo week — {label}', 'hi': 'आपका Arogo हफ़्ता — {label}'},
    'email.digest_greeting': {'en': 'Hi {name},', 'hi': 'नमस्ते {name},'},
    'email.digest_there':    {'en': 'there', 'hi': 'दोस्त'},
    'email.digest_week':     {'en': 'Your week: {label}', 'hi': 'आपका हफ़्ता: {label}'},
    'email.digest_week_scored': {'en': 'Your week: {label}  ·  {score}/100 across the {tracked} {areas} you track',
                                 'hi': 'आपका हफ़्ता: {label}  ·  आपके {tracked} ट्रैक किए {areas} में {score}/100'},
    'email.digest_area':     {'en': 'area', 'hi': 'क्षेत्र'},
    'email.digest_areas':    {'en': 'areas', 'hi': 'क्षेत्रों'},
    'email.digest_glance':   {'en': 'At a glance:', 'hi': 'एक नज़र में:'},
    'email.digest_wins':     {'en': 'Wins:', 'hi': 'जीत:'},
    'email.digest_watching': {'en': 'Worth watching:', 'hi': 'ध्यान देने योग्य:'},
    'email.digest_open':     {'en': 'Open Arogo: {url}/', 'hi': 'Arogo खोलें: {url}/'},
    'email.digest_unsub':    {'en': 'No longer want these? Unsubscribe: {url}',
                              'hi': 'अब ये नहीं चाहिए? सदस्यता समाप्त करें: {url}'},

    # ── Caregiver digest email ────────────────────────────────────────────
    'email.cg_subject':  {'en': "Your family's week on Arogo — {label}",
                          'hi': 'Arogo पर आपके परिवार का हफ़्ता — {label}'},
    'email.cg_intro':    {'en': "Here's how your family did this week ({label}):",
                          'hi': 'इस हफ़्ते आपके परिवार ने कैसा किया ({label}):'},
    'email.cg_adherence':{'en': '{pct}% of doses taken ({taken}/{total})',
                          'hi': '{taken}/{total} खुराक ली गईं ({pct}%)'},
    'email.cg_no_doses': {'en': 'no scheduled doses this week', 'hi': 'इस हफ़्ते कोई निर्धारित खुराक नहीं'},
    'email.cg_sleep':    {'en': '{h}h avg sleep', 'hi': '{h}घं औसत नींद'},
    'email.cg_symptoms': {'en': '{n} symptom log{s}', 'hi': '{n} लक्षण लॉग'},
    'email.cg_footer':   {'en': 'These are the family members who share their medicines with you.',
                          'hi': 'ये वे परिवार सदस्य हैं जो अपनी दवाइयाँ आपके साथ साझा करते हैं।'},

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


# Languages the server can localize outgoing text (emails, push) into. English
# is always available; a code earns a place here once MESSAGES carries its
# translations. Kept in sync with the client's SUPPORTED_LANGS — add a code to
# both when a real pack lands. Scaffolded (not yet translated): 'ta','te','bn','mr'.
SERVER_LANGS = ('en', 'hi')


def normalize_lang(lang) -> str:
    """Clamp an arbitrary stored code to a supported language; unknown → 'en'.
    user_profile.language may hold any code the client set, so this is the single
    gate that keeps the mailer/scheduler from trying to render an absent pack."""
    code = str(lang or '').strip().lower()[:5]
    return code if code in SERVER_LANGS else 'en'


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
