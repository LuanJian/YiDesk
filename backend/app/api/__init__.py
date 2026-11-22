from fastapi import APIRouter

from app.api import admin, analytics, assets, attachments, auth, audit, backups, callbacks, compliance, devices, dispatch, export, knowledge, licenses, meetings, open as open_api, org, public, qr, softwares, stats, tickets, users

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

api_router.include_router(public.router, prefix="/public", tags=["公开页"])

api_router.include_router(users.router, prefix="/users", tags=["用户"])

api_router.include_router(tickets.router, prefix="/tickets", tags=["工单"])

api_router.include_router(attachments.router, tags=["附件"])

api_router.include_router(knowledge.router, prefix="/knowledge", tags=["知识库"])

api_router.include_router(assets.router, prefix="/assets", tags=["资产"])

api_router.include_router(licenses.router, prefix="/licenses", tags=["软件许可"])

api_router.include_router(softwares.router, prefix="/softwares", tags=["软件列表"])

api_router.include_router(meetings.router, prefix="/meetings", tags=["会议管理"])

api_router.include_router(org.router, prefix="/org-tags", tags=["组织数据"])

api_router.include_router(devices.router, prefix="/network-devices", tags=["网络设备"])

api_router.include_router(compliance.router, prefix="/compliance", tags=["合规巡检"])

api_router.include_router(qr.router, prefix="/qr-tags", tags=["二维码标签"])

api_router.include_router(qr.public_router, prefix="/qr", tags=["扫码页"])

api_router.include_router(stats.router, prefix="/stats", tags=["统计"])

api_router.include_router(analytics.router, prefix="/analytics", tags=["数据看板"])

api_router.include_router(export.router, prefix="/export", tags=["导出"])

api_router.include_router(admin.router, prefix="/admin", tags=["管理"])

api_router.include_router(audit.router, prefix="/admin/audit", tags=["操作审计"])

api_router.include_router(backups.router, prefix="/admin/backups", tags=["数据备份"])

api_router.include_router(dispatch.router, prefix="/admin/dispatch-v2", tags=["派单引擎"])

api_router.include_router(callbacks.router, prefix="/callbacks", tags=["回调"])

api_router.include_router(open_api.router, prefix="/webhooks", tags=["Webhook"])

api_router.include_router(open_api.open_router, prefix="/open", tags=["开放API"])

api_router.include_router(open_api.ad_router, prefix="/ad", tags=["AD联动"])
