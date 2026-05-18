import os
from functools import lru_cache

from openai import OpenAI


@lru_cache(maxsize=1)
def _load_whisper_model():
    try:
        import torch
        import whisper
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing speech dependencies. Install 'torch' and 'openai-whisper'."
        ) from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_name = os.getenv("WHISPER_MODEL", "base")
    return whisper.load_model(model_name, device=device)


def speech_to_text(audio_path: str) -> tuple[str, str]:
    model = _load_whisper_model()
    result = model.transcribe(audio_path)
    transcript = (result.get("text") or "").strip()
    language = result.get("language", "unknown")
    return transcript, language


def translate_and_structure(text: str, chunk_size: int = 4000) -> str:
    if not text:
        return ""

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set.")

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    model = os.getenv("OPENROUTER_MODEL", "gpt-4o-mini")

    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    total_chunks = len(chunks)
    outputs: list[str] = []

    system_message = (
        "تو یک دستیار تخصصی برای تهیه جزوه دانشگاهی هستی. "
        "وظیفه تو تبدیل متن خام به یک جزوه فارسی روان و منظم است. "
        "قوانین مهم:\n"
        "1. فقط محتوای جزوه را بنویس. هیچ توضیح، مقدمه، نتیجه‌گیری یا نظری درباره خود متن ورودی اضافه نکن.\n"
        "2. از هیچ نشانه‌گذاری Markdown استفاده نکن: نه #، نه ##، نه **، نه ---، نه ___.\n"
        "3. برای عناوین اصلی از شماره‌گذاری استفاده کن (مثال: ۱. عنوان).\n"
        "4. برای زیرعناوین از حروف الفبا استفاده کن (مثال: الف. زیرعنوان).\n"
        "5. برای هر نکته یا بولت‌پوینت فقط یک خط شروع‌شده با «- » بنویس.\n"
        "6. هر بولت‌پوینت فقط یک «-» در ابتدا داشته باشد.\n"
        "7. متن را منطقی، روان و منسجم بنویس.\n"
        "8. هیچ جمله‌ای مانند «متن شما...»، «این جزوه...»، «اگر نیاز به توضیح...» اضافه نکن."
    )

    for i, chunk in enumerate(chunks):
        if total_chunks == 1:
            user_prompt = (
                "متن زیر را به فارسی روان ترجمه کن و به صورت جزوه دانشگاهی ساختاردهی کن.\n"
                "فقط محتوای جزوه را بنویس، بدون هیچ توضیح اضافه‌ای:\n\n"
                f"{chunk}"
            )
        else:
            user_prompt = (
                f"این بخش {i + 1} از {total_chunks} بخش متن است.\n"
                "این بخش را به فارسی روان ترجمه کن و به صورت ادامه جزوه دانشگاهی ساختاردهی کن.\n"
                "فقط محتوای این بخش را بنویس، بدون مقدمه یا نتیجه‌گیری:\n\n"
                f"{chunk}"
            )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        outputs.append(response.choices[0].message.content or "")

    return "\n\n".join(outputs).strip()


