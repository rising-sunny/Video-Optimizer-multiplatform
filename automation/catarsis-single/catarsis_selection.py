"""Explicit channel selection for new manual Catarsis requests.

Historical pair requests without requested_channels retain their original shape.
Only the dedicated single operation may select exactly one channel.
"""
CHANNELS = ("stunning-facts-of-history", "stunning-revelations")
SINGLE_OPERATION = "generation_start_single"
SINGLE_TASK = "generate_single_only"


def request_topics(request, channels=CHANNELS):
    if request.get("operation") == SINGLE_OPERATION:
        channel = request.get("channel")
        if channel not in channels:
            raise ValueError("invalid_single_channel")
        return {channel: request.get("topic")}
    return dict(zip(channels, (request["facts_topic"], request["revelations_topic"])))


def task_channels(task, channels=CHANNELS):
    selected = task.get("requested_channels", list(channels))
    if not isinstance(selected, (list, tuple)) or any(c not in channels for c in selected):
        raise ValueError("invalid_generation_channel_selection")
    selected = tuple(selected)
    if task.get("operation") == SINGLE_TASK:
        if len(selected) != 1:
            raise ValueError("invalid_single_generation_task")
    elif task.get("operation") != "generate_only" or selected != tuple(channels):
        raise ValueError("invalid_pair_generation_task")
    if not isinstance(task.get("topics"), dict) or set(task["topics"]) != set(selected):
        raise ValueError("generation_topics_selection_mismatch")
    return selected
