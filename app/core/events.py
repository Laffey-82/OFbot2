from __future__ import annotations

from typing import Any

from bubus import BaseEvent
from pydantic import Field


class BotLifecycleEvent(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class BotConnected(BotLifecycleEvent):
    pass


class BotDisconnected(BotLifecycleEvent):
    pass


class BotReady(BotLifecycleEvent):
    pass


class GroupMessageReceived(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    message_id: str = ""
    user_id: str = ""
    group_id: str = ""
    message: str = ""
    raw_event: dict[str, Any] = Field(default_factory=dict)


class PrivateMessageReceived(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    message_id: str = ""
    user_id: str = ""
    message: str = ""
    raw_event: dict[str, Any] = Field(default_factory=dict)


class NoticeReceived(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    notice_type: str = ""
    user_id: str = ""
    group_id: str = ""
    operator_id: str = ""
    target_id: str = ""
    file_name: str = ""
    file_size: int = 0
    raw_event: dict[str, Any] = Field(default_factory=dict)


class RequestReceived(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    request_type: str = ""
    user_id: str = ""
    group_id: str = ""
    flag: str = ""
    raw_event: dict[str, Any] = Field(default_factory=dict)


class MessageEdited(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    message_id: str = ""
    raw_event: dict[str, Any] = Field(default_factory=dict)


class MessageRecalled(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    message_id: str = ""
    user_id: str = ""
    group_id: str = ""
    operator_id: str = ""
    raw_event: dict[str, Any] = Field(default_factory=dict)


class MemberJoined(NoticeReceived):
    pass


class MemberLeft(NoticeReceived):
    pass


class MemberMuted(NoticeReceived):
    pass


class GroupNameUpdated(NoticeReceived):
    pass


class GroupPoke(NoticeReceived):
    """群戳一戳。"""


class FileUploaded(NoticeReceived):
    """群文件上传。"""


class FriendRequestReceived(RequestReceived):
    pass


class GroupRequestReceived(RequestReceived):
    pass


class PluginLifecycleEvent(BaseEvent):
    plugin_name: str = ""
    version: str = ""
    error: str = ""


class PluginLoaded(PluginLifecycleEvent):
    pass


class PluginUnloaded(PluginLifecycleEvent):
    pass


class PluginReloaded(PluginLifecycleEvent):
    pass


class PluginFailed(PluginLifecycleEvent):
    pass


class CommandParsed(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    user_id: str = ""
    group_id: str = ""
    command_name: str = ""
    args: str = ""


class CommandInvoked(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    user_id: str = ""
    group_id: str = ""
    command_name: str = ""
    args: str = ""
    plugin_name: str = ""


class CommandRejected(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    user_id: str = ""
    group_id: str = ""
    command_name: str = ""
    reason: str = ""


class CommandFailed(BaseEvent):
    bot_id: str = ""
    self_id: str = ""
    user_id: str = ""
    group_id: str = ""
    command_name: str = ""
    error: str = ""


class TaskTriggered(BaseEvent):
    task_id: str = ""
    task_name: str = ""


class TaskCompleted(BaseEvent):
    task_id: str = ""
    task_name: str = ""


class TaskFailed(BaseEvent):
    task_id: str = ""
    task_name: str = ""
    error: str = ""


class WorkflowRunFailed(BaseEvent):
    workflow_id: int = 0
    workflow_name: str = ""
    run_id: int = 0
    error: str = ""


class TaskAutoDisabled(BaseEvent):
    task_id: str = ""
    task_name: str = ""
    reason: str = ""


class WorkflowAutoDisabled(BaseEvent):
    workflow_id: int = 0
    workflow_name: str = ""
    reason: str = ""


class TaskAutoReenabled(BaseEvent):
    task_id: str = ""
    task_name: str = ""
    reason: str = ""


class WorkflowAutoReenabled(BaseEvent):
    workflow_id: int = 0
    workflow_name: str = ""
    reason: str = ""


class RecordChanged(BaseEvent):
    action: str = ""
    record_type: str = ""
    record_id: int = 0


class RecordStatusChanged(BaseEvent):
    machine_name: str = ""
    from_status: str = ""
    to_status: str = ""


class WebhookReceived(BaseEvent):
    name: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
