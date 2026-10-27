import json
import re
from json_repair import repair_json
from pydantic import ValidationError

from app.config import settings
from app.llm.gateway import gateway


class StructuredOutputError(RuntimeError):
    pass


def parse_output(text, schema):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start:end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = repair_json(text, return_objects=True)
    return schema.model_validate(value)


async def structured(name, inputs, schema, project_id, version_id=None, validate=None):
    messages = [{"role": "user", "content": "仅输出符合此 Schema 的 JSON：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)}]
    for attempt in range(settings.structured_max_retry + 1):
        raw = await gateway.complete(name, inputs, messages, project_id, version_id)
        try:
            result = parse_output(raw, schema)
            if validate:
                validate(result)
            return result
        except (ValidationError, ValueError) as error:
            messages.extend([{"role": "assistant", "content": raw}, {"role": "user", "content": f"输出校验失败，请修正并返回完整 JSON：{error}"}])
            if attempt == settings.structured_max_retry:
                raise StructuredOutputError(f"{name} 结构或业务校验失败：{error}") from error
