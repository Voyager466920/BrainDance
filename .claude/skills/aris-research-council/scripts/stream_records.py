"""Read structured Claude message blocks, retaining all raw events elsewhere.

System notifications legitimately carry a string `message`; JSONL can also
contain scalar values and text blocks. None of these are successful tool calls.
"""


def message(event):
    value=event.get('message') if isinstance(event,dict) else None
    return value if isinstance(value,dict) else {}


def blocks(event):
    content=message(event).get('content',[])
    return [item for item in content if isinstance(item,dict)] if isinstance(content,list) else []
