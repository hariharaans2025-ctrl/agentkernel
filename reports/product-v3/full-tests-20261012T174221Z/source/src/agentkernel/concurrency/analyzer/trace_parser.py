import re

from pydantic import BaseModel


class TimelineEvent(BaseModel):
    thread: str
    event: str
    resource: str


def parse_timeline(text: str) -> list[TimelineEvent]:
    """Only explicit fixture/tool events, never inferred scheduler reconstruction."""
    pattern = r"^(T\d+)\s+(LOCK|WAIT|UNLOCK)\s*(?:\(\s*([\w.-]+)\s*\)|\s+([\w.-]+))\s*$"
    return [TimelineEvent(thread=m[1], event=m[2].upper(), resource=m[3] or m[4])
            for m in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE)]
