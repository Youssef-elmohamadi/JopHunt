from datetime import datetime, timezone
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl
from extractor import extract_urls_from_message, filter_target_platform_urls


class MockMessage:
    def __init__(self, raw_text: str, entities=None):
        self.raw_text = raw_text
        self.entities = entities or []
        self.media = None
        self.id = 101
        self.date = datetime.now(timezone.utc)


def test_plain_urls_extraction():
    text = (
        "مرحبا، مطلوب مطور بايثون لمشروع أتمتة.\n"
        "تفاصيل المشروع: https://mostaql.com/projects/1234567\n"
        "وهذا رابط لمعرض الأعمال https://khamsat.com/user/myprofile."
    )
    msg = MockMessage(raw_text=text)
    urls = extract_urls_from_message(msg)
    assert "https://mostaql.com/projects/1234567" in urls
    assert "https://khamsat.com/user/myprofile" in urls

    target_urls = filter_target_platform_urls(urls)
    assert len(target_urls) == 2


def test_text_url_entity_extraction():
    text = "اضغط هنا للتقديم على الوظيفة أو تواصل معنا."
    entity = MessageEntityTextUrl(offset=0, length=9, url="https://nafezly.com/projects/98765")
    msg = MockMessage(raw_text=text, entities=[entity])

    urls = extract_urls_from_message(msg)
    assert urls == ["https://nafezly.com/projects/98765"]
    target_urls = filter_target_platform_urls(urls)
    assert target_urls == ["https://nafezly.com/projects/98765"]


def test_non_target_urls():
    text = "تابعنا على تويتر https://x.com/tech_jobs أو تفضل بزيارة https://google.com"
    msg = MockMessage(raw_text=text)
    urls = extract_urls_from_message(msg)
    assert len(urls) == 2
    target_urls = filter_target_platform_urls(urls)
    assert len(target_urls) == 0


if __name__ == "__main__":
    test_plain_urls_extraction()
    test_text_url_entity_extraction()
    test_non_target_urls()
    print("All extractor tests passed successfully!")
