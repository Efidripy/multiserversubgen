
    # ------------------------------------------------------------------
    # Client IP tracking
    # ------------------------------------------------------------------

    def get_client_ips(self, node: Dict, email: str) -> Dict:
        """POST /panel/api/clients/ips/{email} — active connection IPs."""
        s, base_url = self._get_session(node)
        if not s: return {"error": "login failed", "ips": []}
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/ips/{email}")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"email": email, "ips": data.get("obj") or []}
            return {"error": f"HTTP {res.status_code}", "ips": []}
        except Exception as exc:
            return {"error": str(exc), "ips": []}

    def clear_client_ips(self, node: Dict, email: str) -> bool:
        """POST /panel/api/clients/clearIps/{email} — reset IP connection log."""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/clearIps/{email}")
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("clear_client_ips %s/%s: %s", node["name"], email, exc)
            return False

    def get_last_online(self, node: Dict, emails: List[str] = None) -> Dict:
        """POST /panel/api/clients/lastOnline — last-seen timestamps."""
        s, base_url = self._get_session(node)
        if not s: return {"error": "login failed", "data": {}}
        try:
            payload = {"emails": emails} if emails else {}
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/lastOnline", json=payload)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "data": data.get("obj") or {}}
            return {"error": f"HTTP {res.status_code}", "data": {}}
        except Exception as exc:
            return {"error": str(exc), "data": {}}

    # ------------------------------------------------------------------
    # Traffic management
    # ------------------------------------------------------------------

    def update_client_traffic(self, node: Dict, email: str, up: int = 0, down: int = 0) -> bool:
        """POST /panel/api/clients/updateTraffic/{email} — set counters directly."""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/updateTraffic/{email}",
                              json={"up": up, "down": down})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("update_client_traffic %s/%s: %s", node["name"], email, exc)
            return False

    def bulk_reset_traffic(self, nodes: List[Dict], emails: List[str]) -> Dict:
        """POST /panel/api/clients/bulkResetTraffic — reset traffic for many clients."""
        results = []
        for node in nodes:
            if self._is_read_only(node):
                results.append({"node": node["name"], "success": False, "error": "read-only"})
                continue
            s, base_url = self._get_session(node)
            if not s:
                results.append({"node": node["name"], "success": False, "error": "login failed"})
                continue
            try:
                res = xui_request(s, "POST", f"{base_url}/panel/api/clients/bulkResetTraffic",
                                  json={"emails": emails})
                ok = self._xui_success(res)
                results.append({"node": node["name"], "success": ok})
            except Exception as exc:
                results.append({"node": node["name"], "success": False, "error": str(exc)})
        ok_count = sum(1 for r in results if r["success"])
        return {"results": results, "successful": ok_count}

    # ------------------------------------------------------------------
    # Client groups
    # ------------------------------------------------------------------

    def get_client_groups(self, node: Dict) -> Dict:
        """GET /panel/api/clients/groups"""
        s, base_url = self._get_session(node)
        if not s: return {"error": "login failed", "groups": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/groups")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"node": node["name"], "groups": data.get("obj") or []}
            return {"error": f"HTTP {res.status_code}", "groups": []}
        except Exception as exc:
            return {"error": str(exc), "groups": []}

    def get_group_emails(self, node: Dict, group_name: str) -> Dict:
        """GET /panel/api/clients/groups/{name}/emails"""
        s, base_url = self._get_session(node)
        if not s: return {"error": "login failed", "emails": []}
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/groups/{group_name}/emails")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return {"group": group_name, "emails": data.get("obj") or []}
            return {"error": f"HTTP {res.status_code}", "emails": []}
        except Exception as exc:
            return {"error": str(exc), "emails": []}

    def create_client_group(self, node: Dict, name: str) -> bool:
        """POST /panel/api/clients/groups/create"""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/create",
                              json={"name": name})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("create_client_group %s: %s", node["name"], exc)
            return False

    def rename_client_group(self, node: Dict, old_name: str, new_name: str) -> bool:
        """POST /panel/api/clients/groups/rename"""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/rename",
                              json={"oldName": old_name, "newName": new_name})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("rename_client_group %s: %s", node["name"], exc)
            return False

    def delete_client_group(self, node: Dict, name: str) -> bool:
        """POST /panel/api/clients/groups/delete"""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/delete",
                              json={"name": name})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("delete_client_group %s: %s", node["name"], exc)
            return False

    def add_to_group(self, node: Dict, group_name: str, emails: List[str]) -> bool:
        """POST /panel/api/clients/groups/bulkAdd"""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/bulkAdd",
                              json={"name": group_name, "emails": emails})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("add_to_group %s: %s", node["name"], exc)
            return False

    def remove_from_group(self, node: Dict, group_name: str, emails: List[str]) -> bool:
        """POST /panel/api/clients/groups/bulkRemove"""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/groups/bulkRemove",
                              json={"name": group_name, "emails": emails})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("remove_from_group %s: %s", node["name"], exc)
            return False

    # ------------------------------------------------------------------
    # Inbound attach / detach
    # ------------------------------------------------------------------

    def attach_client(self, node: Dict, email: str, inbound_ids: List[int]) -> bool:
        """POST /panel/api/clients/{email}/attach — add client to more inbounds."""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/{email}/attach",
                              json={"inboundIds": inbound_ids})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("attach_client %s/%s: %s", node["name"], email, exc)
            return False

    def detach_client(self, node: Dict, email: str, inbound_ids: List[int]) -> bool:
        """POST /panel/api/clients/{email}/detach — remove client from inbounds."""
        if self._is_read_only(node): return False
        s, base_url = self._get_session(node)
        if not s: return False
        try:
            res = xui_request(s, "POST", f"{base_url}/panel/api/clients/{email}/detach",
                              json={"inboundIds": inbound_ids})
            return self._xui_success(res)
        except Exception as exc:
            logger.warning("detach_client %s/%s: %s", node["name"], email, exc)
            return False

    def get_sub_links(self, node: Dict, sub_id: str) -> List[str]:
        """GET /panel/api/clients/subLinks/{subId} — all protocol links for a subscription ID."""
        s, base_url = self._get_session(node)
        if not s: return []
        try:
            res = xui_request(s, "GET", f"{base_url}/panel/api/clients/subLinks/{sub_id}")
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("obj") or []
        except Exception as exc:
            logger.debug("get_sub_links %s/%s: %s", node["name"], sub_id, exc)
        return []
