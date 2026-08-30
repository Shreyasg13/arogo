"""
i18n_server.py — Server-side message catalog for Arogo.

The client UI localizes itself from static/js/app.js (the localStorage 'arogo_lang'
toggle). But emails and Web Push notifications are composed by the Flask app and the
headless scheduler worker — no browser, no localStorage — so they need their own
catalog keyed by the recipient's stored language (user_profile.language).

Usage:
    from i18n_server import tr
    tr(lang, 'push.dose_title', med='Metformin')   # lang is 'en' | 'hi' | 'bn' | 'mr'

`tr` never raises: an unknown key returns the key; a missing translation falls back
to English; a bad .format() returns the unformatted template. English strings are
kept byte-for-byte identical to what the code sent before this catalog existed, so
default-language (en) output — and the tests that assert on it — are unchanged.

A note on {s}. Three English templates carry a bare {s} that the caller fills with
'' or 's' to pluralise ("1 day" / "2 days"). That is an English-only device — no
other language here forms plurals by appending a letter — so the translations omit
it entirely and str.format simply ignores the extra field. Do not "fix" a
translation by adding {s} back into it.
"""
from __future__ import annotations

# key -> {'en': template, 'hi': …, 'bn': …, 'mr': …}. Templates use str.format
# named fields; every language's template must carry the SAME field names (bar
# {s} above), which tests/test_i18n_server.py enforces.
MESSAGES: dict[str, dict[str, str]] = {
    # ── Push: dose reminders ──────────────────────────────────────────────
    'push.dose_title':      {'en': '💊 Time for {med}',
                             'hi': '💊 {med} का समय',
                             'bn': '💊 {med}-এর সময়',
                             'mr': '💊 {med} ची वेळ'},
    'push.dose_when_early': {'en': 'Due at {time} · in ~{min} min',
                             'hi': '{time} पर देय · ~{min} मिनट में',
                             'bn': '{time}-এ দেয় · ~{min} মিনিটে',
                             'mr': '{time} ला देय · ~{min} मिनिटांत'},
    'push.dose_when_sched': {'en': 'Scheduled at {time}',
                             'hi': '{time} पर निर्धारित',
                             'bn': '{time}-এ নির্ধারিত',
                             'mr': '{time} ला ठरलेली'},
    'push.dose_for':        {'en': ' · for {purpose}',
                             'hi': ' · {purpose} के लिए',
                             'bn': ' · {purpose}-এর জন্য',
                             'mr': ' · {purpose} साठी'},
    'push.dose_with_food':  {'en': ' · take with food',
                             'hi': ' · भोजन के साथ लें',
                             'bn': ' · খাবারের সঙ্গে নিন',
                             'mr': ' · जेवणासोबत घ्या'},
    'push.act_taken':       {'en': '✓ Taken',   'hi': '✓ लिया',
                             'bn': '✓ নেওয়া হয়েছে', 'mr': '✓ घेतली'},
    'push.act_later':       {'en': 'Later',     'hi': 'बाद में',
                             'bn': 'পরে',        'mr': 'नंतर'},
    'push.snooze_title':    {'en': '💊 Still due: {med}',
                             'hi': '💊 अब भी देय: {med}',
                             'bn': '💊 এখনও বাকি: {med}',
                             'mr': '💊 अजूनही बाकी: {med}'},
    'push.snooze_body':     {'en': 'Snoozed reminder — take it when you can.',
                             'hi': 'टाला गया रिमाइंडर — जब हो सके तब लें।',
                             'bn': 'পিছিয়ে দেওয়া রিমাইন্ডার — যখন পারেন নিয়ে নিন।',
                             'mr': 'पुढे ढकललेली आठवण — जमेल तेव्हा घ्या.'},

    # ── Push: water ───────────────────────────────────────────────────────
    'push.water_title': {'en': '💧 Hydration check', 'hi': '💧 पानी की जाँच',
                         'bn': '💧 জলপান পরীক্ষা',   'mr': '💧 पाण्याची तपासणी'},
    'push.water_body':  {'en': "You're behind on water — about {ml}ml to go today.",
                         'hi': 'आप पानी में पीछे हैं — आज लगभग {ml}ml बाकी।',
                         'bn': 'আপনি জলপানে পিছিয়ে আছেন — আজ প্রায় {ml}ml বাকি।',
                         'mr': 'तुम्ही पाण्यात मागे आहात — आज सुमारे {ml}ml बाकी.'},
    'push.water_act':   {'en': '💧 {ml}ml', 'hi': '💧 {ml}ml',
                         'bn': '💧 {ml}ml', 'mr': '💧 {ml}ml'},

    # ── Push: evening habit / sleep / mood ────────────────────────────────
    'push.habit_title': {'en': '⭐ Evening habit check', 'hi': '⭐ शाम की आदत जाँच',
                         'bn': '⭐ সন্ধ্যার অভ্যাস পরীক্ষা', 'mr': '⭐ संध्याकाळची सवय-तपासणी'},
    'push.habit_body':  {'en': 'Tick off what you completed today.',
                         'hi': 'आज जो पूरा किया उसे टिक करें।',
                         'bn': 'আজ যা সম্পন্ন করেছেন তাতে টিক দিন।',
                         'mr': 'आज जे पूर्ण केले त्यावर खूण करा.'},
    'push.sleep_title': {'en': '🌙 Wind-down time', 'hi': '🌙 आराम का समय',
                         'bn': '🌙 বিশ্রামের সময়',   'mr': '🌙 आरामाची वेळ'},
    'push.sleep_body':  {'en': "Log last night's sleep and get ready for bed.",
                         'hi': 'बीती रात की नींद दर्ज करें और सोने की तैयारी करें।',
                         'bn': 'গত রাতের ঘুম নথিভুক্ত করুন এবং শোওয়ার প্রস্তুতি নিন।',
                         'mr': 'काल रात्रीची झोप नोंदवा आणि झोपण्याची तयारी करा.'},
    'push.mood_title':  {'en': '😊 How was your day?', 'hi': '😊 आपका दिन कैसा रहा?',
                         'bn': '😊 আপনার দিন কেমন কাটল?', 'mr': '😊 तुमचा दिवस कसा गेला?'},
    'push.mood_body':   {'en': 'A one-line journal entry keeps the streak alive.',
                         'hi': 'एक पंक्ति की डायरी स्ट्रीक बनाए रखती है।',
                         'bn': 'এক লাইনের ডায়েরি ধারাবাহিকতা ধরে রাখে।',
                         'mr': 'एका ओळीची दैनंदिनी मालिका टिकवून ठेवते.'},
    'push.mood_good':     {'en': '😊 Good',      'hi': '😊 अच्छा',
                           'bn': '😊 ভালো',       'mr': '😊 छान'},
    'push.mood_notgreat': {'en': '😕 Not great', 'hi': '😕 अच्छा नहीं',
                           'bn': '😕 তেমন ভালো নয়', 'mr': '😕 फारसे छान नाही'},

    # ── Push: measurement check-ins ───────────────────────────────────────
    'push.meas_bp_title':   {'en': '🩺 Check your blood pressure',
                             'hi': '🩺 अपना रक्तचाप जाँचें',
                             'bn': '🩺 আপনার রক্তচাপ দেখুন',
                             'mr': '🩺 तुमचा रक्तदाब तपासा'},
    'push.meas_bp_body':    {'en': 'Take a reading and log it in Arogo.',
                             'hi': 'एक रीडिंग लें और Arogo में दर्ज करें।',
                             'bn': 'একটি পাঠ নিন এবং Arogo-তে নথিভুক্ত করুন।',
                             'mr': 'एक नोंद घ्या आणि ती Arogo मध्ये नोंदवा.'},
    'push.meas_sugar_title':{'en': '🩸 Check your blood sugar',
                             'hi': '🩸 अपना रक्त शर्करा जाँचें',
                             'bn': '🩸 আপনার রক্তে শর্করা দেখুন',
                             'mr': '🩸 तुमची रक्तशर्करा तपासा'},
    'push.meas_sugar_body': {'en': 'Time for your sugar reading.',
                             'hi': 'आपकी शुगर रीडिंग का समय।',
                             'bn': 'আপনার শর্করা মাপার সময়।',
                             'mr': 'तुमची शर्करा मोजण्याची वेळ.'},
    'push.meas_weight_title':{'en': '⚖️ Time to weigh in',
                              'hi': '⚖️ वज़न लेने का समय',
                              'bn': '⚖️ ওজন নেওয়ার সময়',
                              'mr': '⚖️ वजन घेण्याची वेळ'},
    'push.meas_weight_body':{'en': 'Step on the scale and log your weight.',
                             'hi': 'तराज़ू पर खड़े हों और अपना वज़न दर्ज करें।',
                             'bn': 'ওজন যন্ত্রে দাঁড়ান এবং আপনার ওজন নথিভুক্ত করুন।',
                             'mr': 'वजनकाट्यावर उभे राहा आणि तुमचे वजन नोंदवा.'},
    'push.meas_spo2_title': {'en': '💨 Check your oxygen (SpO2)',
                             'hi': '💨 अपना ऑक्सीजन (SpO2) जाँचें',
                             'bn': '💨 আপনার অক্সিজেন (SpO2) দেখুন',
                             'mr': '💨 तुमचा ऑक्सिजन (SpO2) तपासा'},
    'push.meas_spo2_body':  {'en': 'Take a reading and log it.',
                             'hi': 'एक रीडिंग लें और दर्ज करें।',
                             'bn': 'একটি পাঠ নিন এবং নথিভুক্ত করুন।',
                             'mr': 'एक नोंद घ्या आणि ती नोंदवा.'},
    'push.meas_temp_title': {'en': '🌡️ Check your temperature',
                             'hi': '🌡️ अपना तापमान जाँचें',
                             'bn': '🌡️ আপনার তাপমাত্রা দেখুন',
                             'mr': '🌡️ तुमचे तापमान तपासा'},
    'push.meas_temp_body':  {'en': 'Take a reading and log it.',
                             'hi': 'एक रीडिंग लें और दर्ज करें।',
                             'bn': 'একটি পাঠ নিন এবং নথিভুক্ত করুন।',
                             'mr': 'एक नोंद घ्या आणि ती नोंदवा.'},
    'push.meas_hr_title':   {'en': '💓 Check your heart rate',
                             'hi': '💓 अपनी हृदय गति जाँचें',
                             'bn': '💓 আপনার হৃৎস্পন্দন দেখুন',
                             'mr': '💓 तुमची हृदयगती तपासा'},
    'push.meas_hr_body':    {'en': 'Take a reading and log it.',
                             'hi': 'एक रीडिंग लें और दर्ज करें।',
                             'bn': 'একটি পাঠ নিন এবং নথিভুক্ত করুন।',
                             'mr': 'एक नोंद घ्या आणि ती नोंदवा.'},
    'push.meas_generic_title':{'en': '🩺 Health check-in', 'hi': '🩺 स्वास्थ्य जाँच',
                               'bn': '🩺 স্বাস্থ্য পরীক্ষা', 'mr': '🩺 आरोग्य तपासणी'},
    'push.meas_generic_body':{'en': 'Take your reading and log it.',
                              'hi': 'अपनी रीडिंग लें और दर्ज करें।',
                              'bn': 'আপনার পাঠ নিন এবং নথিভুক্ত করুন।',
                              'mr': 'तुमची नोंद घ्या आणि ती नोंदवा.'},

    # ── Push: refill + appointment ────────────────────────────────────────
    'push.refill_title':  {'en': '🔄 Refill {med}', 'hi': '🔄 {med} रिफिल करें',
                           'bn': '🔄 {med} আবার ভরুন', 'mr': '🔄 {med} पुन्हा भरा'},
    'push.refill_body':   {'en': 'About {days} day{s} of pills left.',
                           'hi': 'लगभग {days} दिन की गोलियाँ बाकी।',
                           'bn': 'প্রায় {days} দিনের ওষুধ বাকি।',
                           'mr': 'सुमारे {days} दिवसांच्या गोळ्या शिल्लक.'},
    'push.appt_tomorrow': {'en': 'Tomorrow', 'hi': 'कल',
                           'bn': 'আগামীকাল',  'mr': 'उद्या'},
    'push.appt_today':    {'en': 'Today',    'hi': 'आज',
                           'bn': 'আজ',        'mr': 'आज'},
    'push.appt_in_days':  {'en': 'In {days} days', 'hi': '{days} दिन में',
                           'bn': '{days} দিনে',     'mr': '{days} दिवसांत'},
    'push.appt_at':       {'en': ' at {time}', 'hi': ' {time} बजे',
                           'bn': ' {time}-এ',   'mr': ' {time} वाजता'},

    # ── Email: verification ───────────────────────────────────────────────
    'email.verify_subject': {'en': 'Verify your Arogo email',
                             'hi': 'अपना Arogo ईमेल सत्यापित करें',
                             'bn': 'আপনার Arogo ইমেল যাচাই করুন',
                             'mr': 'तुमचा Arogo ईमेल पडताळा'},
    'email.verify_body': {
        'en': ('Welcome to Arogo!\n\n'
               'Confirm your email address by opening this link (valid for 24 hours):\n\n'
               '    {link}\n\n'
               "If you didn't create an Arogo account, you can ignore this email.\n"),
        'hi': ('Arogo में आपका स्वागत है!\n\n'
               'इस लिंक को खोलकर अपना ईमेल पता पुष्टि करें (24 घंटे के लिए मान्य):\n\n'
               '    {link}\n\n'
               'यदि आपने Arogo खाता नहीं बनाया, तो इस ईमेल को अनदेखा करें।\n'),
        'bn': ('Arogo-তে আপনাকে স্বাগত!\n\n'
               'এই লিঙ্কটি খুলে আপনার ইমেল ঠিকানা নিশ্চিত করুন (২৪ ঘণ্টার জন্য বৈধ):\n\n'
               '    {link}\n\n'
               'আপনি যদি Arogo অ্যাকাউন্ট তৈরি না করে থাকেন, এই ইমেলটি উপেক্ষা করুন।\n'),
        'mr': ('Arogo मध्ये तुमचे स्वागत!\n\n'
               'ही लिंक उघडून तुमचा ईमेल पत्ता नक्की करा (२४ तासांसाठी वैध):\n\n'
               '    {link}\n\n'
               'तुम्ही Arogo खाते तयार केले नसेल, तर हा ईमेल दुर्लक्षित करा.\n'),
    },

    # ── Email: password reset ─────────────────────────────────────────────
    'email.reset_subject': {'en': 'Reset your Arogo password',
                            'hi': 'अपना Arogo पासवर्ड रीसेट करें',
                            'bn': 'আপনার Arogo পাসওয়ার্ড রিসেট করুন',
                            'mr': 'तुमचा Arogo पासवर्ड नव्याने ठरवा'},
    'email.reset_body': {
        'en': ('Someone requested a password reset for your Arogo account.\n\n'
               'Open this link to choose a new password (valid for 1 hour):\n\n'
               '    {link}\n\n'
               "If this wasn't you, ignore this email — your password is unchanged.\n"),
        'hi': ('किसी ने आपके Arogo खाते के लिए पासवर्ड रीसेट का अनुरोध किया।\n\n'
               'नया पासवर्ड चुनने के लिए यह लिंक खोलें (1 घंटे के लिए मान्य):\n\n'
               '    {link}\n\n'
               'यदि यह आप नहीं थे, तो इस ईमेल को अनदेखा करें — आपका पासवर्ड अपरिवर्तित है।\n'),
        'bn': ('কেউ আপনার Arogo অ্যাকাউন্টের পাসওয়ার্ড রিসেট করতে চেয়েছে।\n\n'
               'নতুন পাসওয়ার্ড বেছে নিতে এই লিঙ্কটি খুলুন (১ ঘণ্টার জন্য বৈধ):\n\n'
               '    {link}\n\n'
               'এটি আপনি না হলে ইমেলটি উপেক্ষা করুন — আপনার পাসওয়ার্ড অপরিবর্তিত আছে।\n'),
        'mr': ('कोणीतरी तुमच्या Arogo खात्याचा पासवर्ड नव्याने ठरवण्याची विनंती केली आहे.\n\n'
               'नवा पासवर्ड निवडण्यासाठी ही लिंक उघडा (१ तासासाठी वैध):\n\n'
               '    {link}\n\n'
               'हे तुम्ही नसाल, तर हा ईमेल दुर्लक्षित करा — तुमचा पासवर्ड बदललेला नाही.\n'),
    },

    # ── Weekly digest: headline / wins / concerns / highlight labels ──────
    'digest.headline_empty':  {'en': 'Nothing logged yet — start tracking and your progress will show up here.',
                               'hi': 'अभी कुछ दर्ज नहीं — ट्रैक करना शुरू करें और आपकी प्रगति यहाँ दिखेगी।',
                               'bn': 'এখনও কিছু নথিভুক্ত হয়নি — নথি রাখা শুরু করুন, আপনার অগ্রগতি এখানে দেখা যাবে।',
                               'mr': 'अजून काहीही नोंदवलेले नाही — नोंद ठेवायला सुरुवात करा, तुमची प्रगती इथे दिसेल.'},
    'digest.headline_strong': {'en': "Strong week — you're building good habits 💪",
                               'hi': 'शानदार हफ़्ता — आप अच्छी आदतें बना रहे हैं 💪',
                               'bn': 'দারুণ সপ্তাহ — আপনি ভালো অভ্যাস গড়ছেন 💪',
                               'mr': 'उत्तम आठवडा — तुम्ही चांगल्या सवयी घडवत आहात 💪'},
    'digest.headline_solid':  {'en': 'Solid week overall, with a few areas to improve',
                               'hi': 'कुल मिलाकर ठोस हफ़्ता, कुछ क्षेत्रों में सुधार की गुंजाइश',
                               'bn': 'সব মিলিয়ে ভালো সপ্তাহ, কয়েকটি জায়গায় উন্নতির সুযোগ আছে',
                               'mr': 'एकंदरीत चांगला आठवडा, काही ठिकाणी सुधारणेला वाव'},
    'digest.headline_mixed':  {'en': 'Mixed week — some wins, some things to work on',
                               'hi': 'मिला-जुला हफ़्ता — कुछ जीत, कुछ पर काम बाकी',
                               'bn': 'মেশানো সপ্তাহ — কিছু সাফল্য, কিছু নিয়ে কাজ বাকি',
                               'mr': 'संमिश्र आठवडा — काही यश, काहींवर काम बाकी'},
    'digest.headline_tough':  {'en': 'Tough week — small steps still count. Keep going.',
                               'hi': 'कठिन हफ़्ता — छोटे कदम भी मायने रखते हैं। लगे रहें।',
                               'bn': 'কঠিন সপ্তাহ — ছোট পদক্ষেপও গোনায় ধরা হয়। চালিয়ে যান।',
                               'mr': 'कठीण आठवडा — छोटी पावलेही मोजली जातात. चालू ठेवा.'},

    'digest.win_sleep':     {'en': 'Averaged {h}h sleep across {nights} of 7 nights',
                             'hi': '7 में से {nights} रातों में औसतन {h}घं नींद',
                             'bn': '৭ রাতের মধ্যে {nights} রাতে গড়ে {h} ঘণ্টা ঘুম',
                             'mr': '७ पैकी {nights} रात्रींत सरासरी {h} तास झोप'},
    'digest.win_workouts':  {'en': '{days} workout days this week — great consistency',
                             'hi': 'इस हफ़्ते {days} कसरत दिन — बढ़िया निरंतरता',
                             'bn': 'এই সপ্তাহে {days} দিন ব্যায়াম — চমৎকার ধারাবাহিকতা',
                             'mr': 'या आठवड्यात {days} दिवस व्यायाम — उत्तम सातत्य'},
    'digest.win_habits':    {'en': '{pct}% habit completion — nearly perfect week',
                             'hi': '{pct}% आदत पूर्णता — लगभग सटीक हफ़्ता',
                             'bn': '{pct}% অভ্যাস সম্পন্ন — প্রায় নিখুঁত সপ্তাহ',
                             'mr': '{pct}% सवयी पूर्ण — जवळजवळ निर्दोष आठवडा'},
    'digest.win_hydration': {'en': 'Well hydrated — averaged {ml}ml/day',
                             'hi': 'अच्छी हाइड्रेशन — औसतन {ml}ml/दिन',
                             'bn': 'ভালো জলপান — গড়ে {ml}ml/দিন',
                             'mr': 'चांगले पाणी — सरासरी {ml}ml/दिवस'},
    'digest.win_burned':    {'en': '{kcal} kcal burned through exercise',
                             'hi': 'कसरत से {kcal} kcal जलाई',
                             'bn': 'ব্যায়ামে {kcal} kcal পোড়ানো হয়েছে',
                             'mr': 'व्यायामातून {kcal} kcal जाळल्या'},

    'digest.concern_sleep_low':   {'en': 'Sleep averaged {h}h across {nights} nights — under the 7–9h usually recommended. Early night this week?',
                                   'hi': 'नींद {nights} रातों में औसतन {h}घं रही — सामान्यतः अनुशंसित 7–9घं से कम। इस हफ़्ते जल्दी सोएँ?',
                                   'bn': '{nights} রাতে ঘুম গড়ে {h} ঘণ্টা — সাধারণত পরামর্শ দেওয়া ৭–৯ ঘণ্টার কম। এই সপ্তাহে একটু তাড়াতাড়ি শোবেন?',
                                   'mr': '{nights} रात्रींत झोप सरासरी {h} तास — सर्वसाधारणपणे सुचवलेल्या ७–९ तासांहून कमी. या आठवड्यात लवकर झोपाल?'},
    'digest.concern_sleep_short': {'en': 'Sleep was a bit short ({h}h avg over {nights} nights). Aim for 7h+ tonight.',
                                   'hi': 'नींद थोड़ी कम रही ({nights} रातों में {h}घं औसत)। आज 7घं+ का लक्ष्य रखें।',
                                   'bn': 'ঘুম একটু কম হয়েছে ({nights} রাতে গড়ে {h} ঘণ্টা)। আজ ৭ ঘণ্টার বেশি লক্ষ্য রাখুন।',
                                   'mr': 'झोप थोडी कमी झाली ({nights} रात्रींत सरासरी {h} तास). आज ७ तासांहून अधिक झोपण्याचे लक्ष्य ठेवा.'},
    'digest.concern_workouts':    {'en': 'Only {days} workout day this week. Try for 3+.',
                                   'hi': 'इस हफ़्ते केवल {days} कसरत दिन। 3+ की कोशिश करें।',
                                   'bn': 'এই সপ্তাহে মাত্র {days} দিন ব্যায়াম। ৩ দিনের বেশি চেষ্টা করুন।',
                                   'mr': 'या आठवड्यात फक्त {days} दिवस व्यायाम. ३ हून अधिक दिवसांचा प्रयत्न करा.'},
    'digest.concern_habits':      {'en': 'Habits only {pct}% complete. Consider removing habits that no longer fit.',
                                   'hi': 'आदतें केवल {pct}% पूर्ण। जो आदतें अब फिट नहीं बैठतीं उन्हें हटाने पर विचार करें।',
                                   'bn': 'অভ্যাস মাত্র {pct}% সম্পন্ন। যেগুলি আর মানানসই নয় সেগুলি সরানোর কথা ভাবুন।',
                                   'mr': 'सवयी फक्त {pct}% पूर्ण. आता जुळत नसलेल्या सवयी काढून टाकण्याचा विचार करा.'},
    'digest.concern_symptom':     {'en': '{name} appeared {count} time{s} this week. Worth noting if it continues.',
                                   'hi': '{name} इस हफ़्ते {count} बार आया। जारी रहे तो ध्यान देने योग्य।',
                                   'bn': '{name} এই সপ্তাহে {count} বার দেখা গেছে। চলতে থাকলে লক্ষ রাখার মতো।',
                                   'mr': '{name} या आठवड्यात {count} वेळा दिसले. चालू राहिल्यास लक्ष देण्याजोगे.'},
    'digest.concern_hydration':   {'en': 'Hydration was low ({ml}ml avg, goal {goal}ml). Try a water reminder.',
                                   'hi': 'हाइड्रेशन कम रही ({ml}ml औसत, लक्ष्य {goal}ml)। पानी का रिमाइंडर आज़माएँ।',
                                   'bn': 'জলপান কম হয়েছে (গড়ে {ml}ml, লক্ষ্য {goal}ml)। জলের একটি রিমাইন্ডার চালু করে দেখুন।',
                                   'mr': 'पाणी कमी झाले (सरासरी {ml}ml, लक्ष्य {goal}ml). पाण्याची आठवण लावून पाहा.'},

    'digest.hl_sleep':    {'en': 'Avg sleep ({nights}/7 nights)',
                           'hi': 'औसत नींद ({nights}/7 रातें)',
                           'bn': 'গড় ঘুম ({nights}/৭ রাত)',
                           'mr': 'सरासरी झोप ({nights}/७ रात्री)'},
    'digest.hl_workouts': {'en': 'Workout days', 'hi': 'कसरत दिन',
                           'bn': 'ব্যায়ামের দিন', 'mr': 'व्यायामाचे दिवस'},
    'digest.hl_habits':   {'en': 'Habits', 'hi': 'आदतें',
                           'bn': 'অভ্যাস',  'mr': 'सवयी'},
    'digest.hl_water':    {'en': 'Avg water', 'hi': 'औसत पानी',
                           'bn': 'গড় জল',     'mr': 'सरासरी पाणी'},
    'digest.hl_burned':   {'en': 'Cal burned', 'hi': 'कैलोरी जली',
                           'bn': 'পোড়ানো ক্যালরি', 'mr': 'जाळलेल्या कॅलरी'},

    # ── Weekly digest email scaffolding ───────────────────────────────────
    'email.digest_subject':  {'en': 'Your Arogo week — {label}',
                              'hi': 'आपका Arogo हफ़्ता — {label}',
                              'bn': 'Arogo-তে আপনার সপ্তাহ — {label}',
                              'mr': 'Arogo वरचा तुमचा आठवडा — {label}'},
    'email.digest_greeting': {'en': 'Hi {name},', 'hi': 'नमस्ते {name},',
                              'bn': 'নমস্কার {name},', 'mr': 'नमस्कार {name},'},
    'email.digest_there':    {'en': 'there', 'hi': 'दोस्त',
                              'bn': 'বন্ধু',   'mr': 'मित्रा'},
    'email.digest_week':     {'en': 'Your week: {label}', 'hi': 'आपका हफ़्ता: {label}',
                              'bn': 'আপনার সপ্তাহ: {label}', 'mr': 'तुमचा आठवडा: {label}'},
    'email.digest_week_scored': {'en': 'Your week: {label}  ·  {score}/100 across the {tracked} {areas} you track',
                                 'hi': 'आपका हफ़्ता: {label}  ·  आपके {tracked} ट्रैक किए {areas} में {score}/100',
                                 'bn': 'আপনার সপ্তাহ: {label}  ·  আপনি যে {tracked}টি {areas} নথিভুক্ত করেন তাতে {score}/100',
                                 'mr': 'तुमचा आठवडा: {label}  ·  तुम्ही नोंद ठेवता त्या {tracked} {areas} मध्ये {score}/100'},
    'email.digest_area':     {'en': 'area', 'hi': 'क्षेत्र',
                              'bn': 'ক্ষেত্র', 'mr': 'क्षेत्र'},
    'email.digest_areas':    {'en': 'areas', 'hi': 'क्षेत्रों',
                              'bn': 'ক্ষেত্র',  'mr': 'क्षेत्रांत'},
    'email.digest_glance':   {'en': 'At a glance:', 'hi': 'एक नज़र में:',
                              'bn': 'এক নজরে:',      'mr': 'एका दृष्टिक्षेपात:'},
    'email.digest_wins':     {'en': 'Wins:', 'hi': 'जीत:',
                              'bn': 'সাফল্য:', 'mr': 'यश:'},
    'email.digest_watching': {'en': 'Worth watching:', 'hi': 'ध्यान देने योग्य:',
                              'bn': 'লক্ষ রাখার মতো:',   'mr': 'लक्ष देण्याजोगे:'},
    'email.digest_open':     {'en': 'Open Arogo: {url}/', 'hi': 'Arogo खोलें: {url}/',
                              'bn': 'Arogo খুলুন: {url}/', 'mr': 'Arogo उघडा: {url}/'},
    'email.digest_unsub':    {'en': 'No longer want these? Unsubscribe: {url}',
                              'hi': 'अब ये नहीं चाहिए? सदस्यता समाप्त करें: {url}',
                              'bn': 'আর চান না? বন্ধ করুন: {url}',
                              'mr': 'आता हे नको? सदस्यत्व थांबवा: {url}'},

    # ── Caregiver digest email ────────────────────────────────────────────
    'email.cg_subject':  {'en': "Your family's week on Arogo — {label}",
                          'hi': 'Arogo पर आपके परिवार का हफ़्ता — {label}',
                          'bn': 'Arogo-তে আপনার পরিবারের সপ্তাহ — {label}',
                          'mr': 'Arogo वरचा तुमच्या कुटुंबाचा आठवडा — {label}'},
    'email.cg_intro':    {'en': "Here's how your family did this week ({label}):",
                          'hi': 'इस हफ़्ते आपके परिवार ने कैसा किया ({label}):',
                          'bn': 'এই সপ্তাহে আপনার পরিবার কেমন করল ({label}):',
                          'mr': 'या आठवड्यात तुमच्या कुटुंबाने कसे केले ({label}):'},
    'email.cg_adherence':{'en': '{pct}% of doses taken ({taken}/{total})',
                          'hi': '{taken}/{total} खुराक ली गईं ({pct}%)',
                          'bn': '{total}-এর মধ্যে {taken}টি ডোজ নেওয়া হয়েছে ({pct}%)',
                          'mr': '{total} पैकी {taken} मात्रा घेतल्या ({pct}%)'},
    'email.cg_no_doses': {'en': 'no scheduled doses this week',
                          'hi': 'इस हफ़्ते कोई निर्धारित खुराक नहीं',
                          'bn': 'এই সপ্তাহে কোনও নির্ধারিত ডোজ নেই',
                          'mr': 'या आठवड्यात कोणतीही ठरलेली मात्रा नाही'},
    'email.cg_sleep':    {'en': '{h}h avg sleep', 'hi': '{h}घं औसत नींद',
                          'bn': 'গড়ে {h} ঘণ্টা ঘুম', 'mr': 'सरासरी {h} तास झोप'},
    'email.cg_symptoms': {'en': '{n} symptom log{s}', 'hi': '{n} लक्षण लॉग',
                          'bn': '{n}টি উপসর্গের নথি', 'mr': '{n} लक्षण-नोंदी'},
    'email.cg_footer':   {'en': 'These are the family members who share their medicines with you.',
                          'hi': 'ये वे परिवार सदस्य हैं जो अपनी दवाइयाँ आपके साथ साझा करते हैं।',
                          'bn': 'এঁরা সেই পরিবারের সদস্য যাঁরা তাঁদের ওষুধ আপনার সঙ্গে ভাগ করেন।',
                          'mr': 'हे ते कुटुंबीय आहेत जे त्यांची औषधे तुमच्यासोबत वाटतात.'},

    # ── Email: family invite ──────────────────────────────────────────────
    'email.invite_subject': {'en': '{inviter} invited you to their Arogo family group',
                             'hi': '{inviter} ने आपको अपने Arogo परिवार समूह में आमंत्रित किया',
                             'bn': '{inviter} আপনাকে তাঁদের Arogo পরিবার গোষ্ঠীতে আমন্ত্রণ জানিয়েছেন',
                             'mr': '{inviter} यांनी तुम्हाला त्यांच्या Arogo कुटुंब-गटात बोलावले आहे'},
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
        'bn': ('{inviter} আপনাকে Arogo-তে "{group}" পরিবার গোষ্ঠীতে যোগ দিতে আমন্ত্রণ জানিয়েছেন।\n\n'
               'পরিবারের সদস্যরা ঠিক কোন স্বাস্থ্য-বিভাগগুলি ভাগ করবেন তা নিজেরাই বেছে নেন —\n'
               'আপনি চালু না করা পর্যন্ত কিছুই দেখা যায় না।\n\n'
               'যোগ দিতে এই লিঙ্কটি খুলুন (৭২ ঘণ্টার জন্য বৈধ):\n\n'
               '    {link}\n\n'
               'যোগ দিতে না চাইলে ইমেলটি উপেক্ষা করুন।\n'),
        'mr': ('{inviter} यांनी तुम्हाला Arogo वरील "{group}" या कुटुंब-गटात सामील होण्यासाठी बोलावले आहे.\n\n'
               'कुटुंबातील सदस्य नेमके कोणते आरोग्य-प्रकार वाटायचे ते स्वतः ठरवतात —\n'
               'तुम्ही चालू करेपर्यंत काहीही दिसत नाही.\n\n'
               'सामील होण्यासाठी ही लिंक उघडा (७२ तासांसाठी वैध):\n\n'
               '    {link}\n\n'
               'सामील व्हायचे नसेल, तर हा ईमेल दुर्लक्षित करा.\n'),
    },
}


# Languages the server can localize outgoing text (emails, push) into. English
# is always available; a code earns a place here once MESSAGES carries its
# translations. Kept in sync with the client's SUPPORTED_LANGS — add a code to
# both when a real pack lands. Scaffolded (not yet translated): 'ta','te'.
#
# bn and mr joined 2026-08-29. Before that a Bengali or Marathi user read a
# fully translated app and then got their dose reminders in English, because
# this tuple — not the pack — decides what the scheduler can send. That is a
# separate axis from the client packs and it has to be moved deliberately.
SERVER_LANGS = ('en', 'hi', 'bn', 'mr')


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
