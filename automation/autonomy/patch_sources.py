"""Small deterministic source changes; fail before writing on an unknown shape."""
import ast


def replace(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError("single_catarsis_source_shape_changed")
    return text.replace(before, after, 1)


def section(text, start, end, transform):
    try:
        a = text.index(start)
        b = text.index(end, a)
    except ValueError:
        raise RuntimeError("single_catarsis_source_shape_changed") from None
    return text[:a] + transform(text[a:b]) + text[b:]


def generation_service(text):
    text = replace(text,
        "OPERATIONS |= {'generation_finish_saved_pair'",
        "OPERATIONS |= {'generation_start_single'}\nOPERATIONS |= {'generation_finish_saved_pair'")
    text = replace(text,
        "            'generation_start': {'operation', 'request_id', 'facts_topic', 'revelations_topic'},",
        "            'generation_start': {'operation', 'request_id', 'facts_topic', 'revelations_topic'},\n"
        "            'generation_start_single': {'operation', 'request_id', 'channel', 'topic'},")
    text = replace(text, "                if operation == 'generation_start':\n",
                   "                if operation in ('generation_start', 'generation_start_single'):\n")
    def start(value):
        value = replace(value,
            "        topics = dict(zip(CHANNELS, (request['facts_topic'], request['revelations_topic'])))",
            "        from catarsis_selection import request_topics\n"
            "        topics = request_topics(request, CHANNELS)")
        value = replace(value, "                    operation='generate_only', publication_allowed=False, style_profile=VERSION)",
            "                    operation='generate_single_only' if len(topics)==1 else 'generate_only',\n"
            "                    requested_channels=list(topics), publication_allowed=False, style_profile=VERSION)")
        value = replace(value, "            channels={c: {'state': 'pending', 'error_code': None} for c in CHANNELS}))",
            "            channels={c: {'state': 'pending', 'error_code': None} for c in topics}))")
        return value
    text = section(text, "    def start(self, request):", "    def repair(self,", start)
    # ast.parse requires indentation at column zero; de-indent only for inspection.
    import textwrap
    def parsed_status(value):
        # Keep all source indentation and unrelated recovery routes unchanged.
        value = replace(value, "        channels = {}\n        for channel in CHANNELS:",
            "        from catarsis_selection import task_channels\n"
            "        selected = task_channels(task, CHANNELS)\n"
            "        channels = {}\n        for channel in selected:")
        value = replace(value, "                error_code=row.get('error_code'), diagnostic=row.get('diagnostic'), quality_approved=row.get('state') == 'ready',",
            "                error_code=row.get('error_code'), diagnostic=row.get('diagnostic'), quality_approved=row.get('state') == 'ready',\n"
            "                approval_sha256=row.get('approval_sha256') if row.get('state') == 'ready' else None,")
        value = replace(value, "        if state == 'ready':\n", "        if state == 'ready' and len(selected) == len(CHANNELS):\n")
        value = replace(value, "        pair_hash = None\n",
            "        if len(selected) == 1:\n"
            "            for channel in CHANNELS:\n"
            "                if channel not in channels:\n"
            "                    channels[channel] = dict(state='not_requested', topic='', quality_approved=False, error_code=None, metadata={}, files={})\n"
            "        pair_hash = None\n")
        value = replace(value, "            batch_id=batch, request_id=task['request_id'], date=task['date'],",
            "            requested_channels=list(selected), generation_mode='single' if len(selected)==1 else 'pair',\n"
            "            batch_id=batch, request_id=task['request_id'], date=task['date'],")
        parsed = textwrap.dedent(value)
        node = ast.parse(parsed).body[0]
        keyword = next(k for n in ast.walk(node) if isinstance(n, ast.Return) and isinstance(n.value, ast.Call)
                       for k in n.value.keywords if k.arg == 'quality_note')
        literal = ast.get_source_segment(parsed, keyword.value)
        return replace(value, literal,
            "('Single-channel generation only. Preview the approved video and full credits before any separately authorized publication to its channel; publish_catarsis_pair does not apply.' if len(selected)==1 else " + literal + ")")
    text = section(text, "    def status(self, batch):", "    def repair_claude_service(self,", parsed_status)
    ast.parse(text)
    return text


def generation_worker(text):
    def perform(value):
        value = replace(value,
            "    if request.get('batch_id') != batch or request.get('operation') != 'generate_only' or request.get('publication_allowed') is not False or set(request.get('topics', {})) != set(CHANNELS):",
            "    from catarsis_selection import task_channels\n"
            "    selected = task_channels(request, CHANNELS)\n"
            "    if request.get('batch_id') != batch or request.get('publication_allowed') is not False:")
        value = replace(value, "    module_names = ('shorts_handoff.py'", "    module_names = ('catarsis_selection.py','generation_service.py','shorts_handoff.py'")
        value = replace(value,
            "    if not music_provider.configured(CHANNELS[1]):\n        raise RuntimeError('epidemic_configuration_required_for_revelations')\n    music_provider.rights(CHANNELS[1])",
            "    if CHANNELS[1] in selected:\n"
            "        if not music_provider.configured(CHANNELS[1]):\n"
            "            raise RuntimeError('epidemic_configuration_required_for_revelations')\n"
            "        music_provider.rights(CHANNELS[1])")
        value = replace(value, "        for channel in CHANNELS:\n", "        for channel in selected:\n")
        value = replace(value, "state='ready' if ready == 2 else 'partial' if ready else 'blocked'",
                        "state='ready' if ready == len(selected) else 'partial' if ready else 'blocked'")
        return value
    text = section(text, "def perform(batch):", "\n\ndef main():", perform)
    ast.parse(text)
    return text


def documentary_service(text):
    text = replace(text,
        "        if parent.documentary.active and op in {'generation_start','generation_revise_style','publication_start','request_today'}:",
        "        if parent.documentary.active and op in {'generation_start','generation_start_single','generation_revise_style','publication_start','request_today'}:")
    ast.parse(text)
    return text
