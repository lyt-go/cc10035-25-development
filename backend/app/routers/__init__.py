"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import cross_module, resource, site_attribution

# 固定前缀的站点归属路由要排在通用 /api/{module} 之前注册。
ROUTERS = [site_attribution, cross_module, resource]
