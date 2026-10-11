# نص أطول من مكانه · Fixing an overflowing text
- الفحص `fit` أو مانع `text_overflow` معناه إن النص مش هيكفي بالحجم المسموح.
- الحلول بالترتيب: (1) جملة أقصر بنفس المعنى، (2) صندوق أكبر جوه منطقة الأمان، (3) آخر حاجة: حجم أصغر بشرط مايقلّش عن الحد الأدنى.
- بعد التعديل شغّل `factory.build` تاني واتأكد إن الفحوصات كلها خضرا.
Order of remedies: shorter wording, larger box inside the safe zone, then a smaller size never below the minimum; rebuild and re-validate.
