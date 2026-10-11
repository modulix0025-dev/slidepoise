"""A brand-new short story used to prove the factory end to end (Phase 3 gate).

Written for this program; the boy and girl Arabic texts are authored separately
(verbs, pronouns, adjectives), and the English texts are their translations.
"""
from __future__ import annotations

from mxstudio.factory.story import Page, Story


def moon_star_story() -> Story:
    return Story(
        key="moon_star",
        title={"ar": "{NAME} ونجمة القمر", "en": "{NAME} and the Moon Star"},
        figure_prompt_male="a cheerful Egyptian boy, about six years old, in blue pajamas",
        figure_prompt_female="a cheerful Egyptian girl, about six years old, in yellow pajamas",
        pages=[
            Page(kind="cover", texts={
                "ar_boy": "{NAME} ونجمة القمر", "ar_girl": "{NAME} ونجمة القمر",
                "en_boy": "{NAME} and the Moon Star", "en_girl": "{NAME} and the Moon Star"},
                scene="the child on a rooftop in Cairo at night, looking at a big friendly moon"),
            Page(kind="scene", texts={
                "ar_boy": "في ليلة هادئة، طلع {NAME} على سطح البيت، ورفع عينه للسماء فشاف نجمة صغيرة بتلمع وتغمز له.",
                "ar_girl": "في ليلة هادئة، طلعت {NAME} على سطح البيت، ورفعت عينها للسماء فشافت نجمة صغيرة بتلمع وتغمز لها.",
                "en_boy": "On a quiet night, {NAME} climbed up to the roof and looked at the sky. A tiny star was twinkling and winking at him.",
                "en_girl": "On a quiet night, {NAME} climbed up to the roof and looked at the sky. A tiny star was twinkling and winking at her."},
                scene="a tiny star winking at the child from the night sky"),
            Page(kind="scene", texts={
                "ar_boy": "قالت النجمة: «أنا تايهة عن القمر يا {NAME}». فمسك {NAME} فانوسه وقال: «ماتخافيش، هوصّلك».",
                "ar_girl": "قالت النجمة: «أنا تايهة عن القمر يا {NAME}». فمسكت {NAME} فانوسها وقالت: «ماتخافيش، هوصّلك».",
                "en_boy": "\"I lost my way to the Moon, {NAME},\" said the star. {NAME} held up his lantern: \"Don't worry, I will take you home.\"",
                "en_girl": "\"I lost my way to the Moon, {NAME},\" said the star. {NAME} held up her lantern: \"Don't worry, I will take you home.\""},
                scene="the child holding a Ramadan lantern next to a small glowing star"),
            Page(kind="scene", texts={
                "ar_boy": "طار {NAME} مع النجمة فوق النيل، ولما وصلوا حضنها القمر وقال: «شكرًا يا بطل، قلبك كبير».",
                "ar_girl": "طارت {NAME} مع النجمة فوق النيل، ولما وصلوا حضنها القمر وقال: «شكرًا يا بطلة، قلبك كبير».",
                "en_boy": "{NAME} flew with the star over the Nile. When they arrived, the Moon hugged her and said: \"Thank you, hero. You have a big heart.\"",
                "en_girl": "{NAME} flew with the star over the Nile. When they arrived, the Moon hugged her and said: \"Thank you, heroine. You have a big heart.\""},
                scene="the child flying over the Nile with the star towards a smiling moon"),
            Page(kind="dedication", texts={
                "ar_boy": "بكل الحب تهدى لـ{NAME}", "ar_girl": "بكل الحب تهدى لـ{NAME}",
                "en_boy": "With all our love, for {NAME}", "en_girl": "With all our love, for {NAME}"},
                figure=False),
            Page(kind="back", figure=False),
        ],
    )
