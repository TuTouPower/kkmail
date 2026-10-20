"""body_preview must be plain text, never raw HTML."""
from email.message import EmailMessage

import web_outlook_app as appmod


def test_build_body_preview_strips_html_only_message():
    msg = EmailMessage()
    msg['Subject'] = 't'
    msg['From'] = 'ChatGPT <noreply@example.com>'
    msg.set_content('<html><body><p>你好 <b>世界</b></p></body></html>', subtype='html')
    preview = appmod.build_body_preview(msg)
    assert '<' not in preview
    assert '你好' in preview
    assert '世界' in preview


def test_build_body_preview_prefers_text_part():
    msg = EmailMessage()
    msg['Subject'] = 't'
    msg['From'] = 'a@b.c'
    msg.set_content('纯文本预览内容')
    msg.add_alternative('<html><body>HTML</body></html>', subtype='html')
    assert appmod.build_body_preview(msg) == '纯文本预览内容'
