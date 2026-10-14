import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from typing import TypeVar

from pydantic import BaseModel
import time
import groq


load_dotenv()

MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def get_llm(temperature: float = 0.0) -> ChatGroq:
    return ChatGroq(model=MODEL_NAME, temperature=temperature)


if __name__ == "__main__":
    llm = get_llm()
    response = llm.invoke("Reply with exactly: Groq connection works.")
    print(response.content)

T = TypeVar("T", bound=BaseModel)


RATE_LIMIT_WAIT_SECONDS = 30


def invoke_structured(schema: type[T], prompt: str, retries: int = 2) -> T:
    structured_llm = get_llm().with_structured_output(
        schema, method="json_schema", strict=True
    )
    feedback = ""
    last_error = ""
    for attempt in range(retries + 1):
        text = prompt
        if feedback:
            text = (
                f"{prompt}\n\nYour previous answer was rejected with this error:\n"
                f"{feedback}\nFix the problem and answer again, following the schema exactly."
            )
        try:
            result = structured_llm.invoke(text)
            if not isinstance(result, schema):
                result = schema.model_validate(result)
            return result
        except groq.RateLimitError as error:
            last_error = str(error)[:500]
            if attempt < retries:
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
        except Exception as error:
            if isinstance(error, groq.APIStatusError) and error.status_code == 413:
                raise RuntimeError(
                    f"prompt is too large for the model's token limit: {str(error)[:300]}"
                ) from error
            last_error = feedback = str(error)[:500]
    raise RuntimeError(f"failed after {retries + 1} attempts: {last_error}")