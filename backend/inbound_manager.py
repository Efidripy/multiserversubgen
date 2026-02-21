"""
Модуль управления инбаундами node panel
Содержит функции для получения, создания, клонирования и удаления инбаундов
"""
import requests
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from xui_session import login_node panel
from utils import parse_field_as_dict

logger = logging.getLogger("sub_manager")


class InboundManager:
    def __init__(self, decrypt_func, encrypt_func=None):
        """Инициализация менеджера инбаундов с функциями шифрования/дешифрования
        
        Args:
            decrypt_func: Функция для расшифровки паролей узлов
            encrypt_func: Опциональная функция для шифрования паролей
        """
        self.decrypt = decrypt_func
        self.encrypt = encrypt_func
    
    def get_all_inbounds(self, nodes: List[Dict]) -> List[Dict]:
        """Получить все инбаунды со всех узлов
        
        Args:
            nodes: Список узлов с конфигурацией
            
        Returns:
            Список инбаундов с метаданными
        """
        inbounds = []
        for node in nodes:
            try:
                node_inbounds = self._fetch_inbounds_from_node(node)
                for ib in node_inbounds:
                    stream = parse_field_as_dict(
                        ib.get("streamSettings"),
                        node_id=node["name"],
                        field_name="streamSettings",
                    )
                    inbound = {
                        "id": ib.get("id"),
                        "node_name": node["name"],
                        "node_ip": node["ip"],
                        "protocol": ib.get("protocol"),
                        "port": ib.get("port"),
                        "remark": ib.get("remark", ""),
                        "enable": ib.get("enable", True),
                        "streamSettings": stream,
                        "settings": parse_field_as_dict(
                            ib.get("settings"),
                            node_id=node["name"],
                            field_name="settings",
                        )
                    }
                    security = stream.get("security", "")
                    inbound["security"] = security
                    inbound["is_reality"] = security == "reality"
                    inbounds.append(inbound)
            except Exception as exc:
                logger.warning(f"Failed to fetch inbounds from {node['name']}: {exc}")
        
        return inbounds
    
    def _fetch_inbounds_from_node(self, node: Dict) -> List[Dict]:
        """Получить инбаунды с конкретного узла"""
        s = requests.Session()
        s.verify = False
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        
        try:
            if not login_node panel(s, base_url, node['user'], self.decrypt(node.get('password', ''))):
                logger.warning(f"node panel login failed for node {node['name']}")
                return []
            res = s.get(f"{base_url}/panel/api/inbounds/list", timeout=5)
            if res.status_code == 200:
                data = res.json()
                return data.get("obj", []) if data.get("success", False) else []
            logger.warning(
                f"node panel {node['name']} inbounds list returned status {res.status_code}; "
                f"response (first 200 chars): {res.text[:200]!r}"
            )
        except Exception as exc:
            logger.warning(f"Request failed for {node['name']}: {exc}")
        
        return []
    
    def add_inbound(self, node: Dict, config: Dict) -> bool:
        """Добавить инбаунд на узел
        
        Args:
            node: Конфигурация узла
            config: Конфигурация инбаунда
            
        Returns:
            True при успехе
        """
        s = requests.Session()
        s.verify = False
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        
        try:
            if not login_node panel(s, base_url, node['user'], self.decrypt(node.get('password', ''))):
                logger.warning(f"node panel login failed for node {node['name']}")
                return False
            res = s.post(f"{base_url}/panel/api/inbounds/add", 
                        json=config, timeout=5)
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to add inbound to {node['name']}: {exc}")
            return False
    
    def clone_inbound(self, source_node: Dict, source_inbound_id: int, 
                     target_nodes: List[Dict], modifications: Optional[Dict] = None) -> Dict:
        """Клонировать инбаунд с одного узла на другие
        
        Args:
            source_node: Узел-источник инбаунда
            source_inbound_id: ID инбаунда-источника
            target_nodes: Список целевых узлов
            modifications: Опциональные модификации (remark, port и т.д.)
            
        Returns:
            Результаты клонирования по узлам
        """
        # Получить исходный инбаунд
        inbounds = self._fetch_inbounds_from_node(source_node)
        source_inbound = next((ib for ib in inbounds if ib.get('id') == source_inbound_id), None)
        
        if not source_inbound:
            return {"error": "Source inbound not found"}
        
        # Создать копию конфигурации с модификациями
        new_config = {
            "port": modifications.get("port", source_inbound.get("port")),
            "protocol": source_inbound.get("protocol"),
            "settings": source_inbound.get("settings", {}),
            "streamSettings": source_inbound.get("streamSettings", {}),
            "remark": modifications.get("remark", source_inbound.get("remark", "")),
            "enable": True,
            "up": 0,
            "down": 0,
            "total": 0,
            "expiryTime": 0
        }
        
        results = []
        for target_node in target_nodes:
            success = self.add_inbound(target_node, new_config)
            results.append({
                "node": target_node["name"],
                "success": success,
                "port": new_config["port"],
                "remark": new_config["remark"]
            })
        
        return {"results": results}
    
    def delete_inbound(self, node: Dict, inbound_id: int) -> bool:
        """Удалить инбаунд с узла"""
        s = requests.Session()
        s.verify = False
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        
        try:
            if not login_node panel(s, base_url, node['user'], self.decrypt(node.get('password', ''))):
                logger.warning(f"node panel login failed for node {node['name']}")
                return False
            res = s.post(f"{base_url}/panel/api/inbounds/del/{inbound_id}", 
                        timeout=5)
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to delete inbound from {node['name']}: {exc}")
            return False
    
    def reset_inbound_traffic(self, node: Dict, inbound_id: int) -> bool:
        """Сбросить статистику инбаунда"""
        s = requests.Session()
        s.verify = False
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        
        try:
            if not login_node panel(s, base_url, node['user'], self.decrypt(node.get('password', ''))):
                logger.warning(f"node panel login failed for node {node['name']}")
                return False
            res = s.post(f"{base_url}/panel/api/inbounds/resetClientTraffic/{inbound_id}", 
                        timeout=5)
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to reset inbound traffic: {exc}")
            return False
    
    def update_inbound(self, node: Dict, inbound_id: int, updates: Dict) -> bool:
        """Обновить параметры инбаунда
        
        Args:
            node: Конфигурация узла
            inbound_id: ID инбаунда
            updates: Обновления (enable, remark, settings и т.д.)
            
        Returns:
            True при успехе
        """
        s = requests.Session()
        s.verify = False
        b_path = node.get("base_path", "").strip("/")
        prefix = f"/{b_path}" if b_path else ""
        base_url = f"https://{node['ip']}:{node['port']}{prefix}"
        
        try:
            if not login_node panel(s, base_url, node['user'], self.decrypt(node.get('password', ''))):
                logger.warning(f"node panel login failed for node {node['name']}")
                return False
            
            # Получить текущую конфигурацию инбаунда
            inbounds = self._fetch_inbounds_from_node(node)
            current = next((ib for ib in inbounds if ib.get('id') == inbound_id), None)
            
            if not current:
                logger.warning(f"Inbound {inbound_id} not found on {node['name']}")
                return False
            
            # Обновить конфигурацию
            current.update(updates)
            
            res = s.post(f"{base_url}/panel/api/inbounds/update/{inbound_id}", 
                        json=current, timeout=5)
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to update inbound on {node['name']}: {exc}")
            return False
    
    def batch_enable_inbounds(self, nodes: List[Dict], inbound_ids: List[int], enable: bool) -> Dict:
        """Включить/выключить несколько инбаундов
        
        Args:
            nodes: Список узлов
            inbound_ids: Список ID инбаундов
            enable: True для включения, False для выключения
            
        Returns:
            Результаты операции
        """
        results = []
        for node in nodes:
            node_inbounds = self._fetch_inbounds_from_node(node)
            for inbound in node_inbounds:
                if inbound.get('id') in inbound_ids:
                    success = self.update_inbound(node, inbound['id'], {"enable": enable})
                    results.append({
                        "node": node["name"],
                        "inbound_id": inbound['id'],
                        "remark": inbound.get('remark', ''),
                        "success": success,
                        "enabled": enable
                    })
        
        return {
            "results": results,
            "total": len(results),
            "successful": sum(1 for r in results if r['success'])
        }
    
    def batch_update_inbounds(self, nodes: List[Dict], inbound_ids: List[int], updates: Dict) -> Dict:
        """Массово обновить несколько инбаундов
        
        Args:
            nodes: Список узлов
            inbound_ids: Список ID инбаундов
            updates: Обновления для применения
            
        Returns:
            Результаты операции
        """
        results = []
        for node in nodes:
            node_inbounds = self._fetch_inbounds_from_node(node)
            for inbound in node_inbounds:
                if inbound.get('id') in inbound_ids:
                    success = self.update_inbound(node, inbound['id'], updates)
                    results.append({
                        "node": node["name"],
                        "inbound_id": inbound['id'],
                        "remark": inbound.get('remark', ''),
                        "success": success
                    })
        
        return {
            "results": results,
            "total": len(results),
            "successful": sum(1 for r in results if r['success'])
        }
    
    def batch_delete_inbounds(self, nodes: List[Dict], inbound_ids: List[int]) -> Dict:
        """Массово удалить несколько инбаундов
        
        Args:
            nodes: Список узлов
            inbound_ids: Список ID инбаундов для удаления
            
        Returns:
            Результаты операции
        """
        results = []
        for node in nodes:
            node_inbounds = self._fetch_inbounds_from_node(node)
            for inbound in node_inbounds:
                if inbound.get('id') in inbound_ids:
                    success = self.delete_inbound(node, inbound['id'])
                    results.append({
                        "node": node["name"],
                        "inbound_id": inbound['id'],
                        "remark": inbound.get('remark', ''),
                        "success": success
                    })
        
        return {
            "results": results,
            "total": len(results),
            "successful": sum(1 for r in results if r['success'])
        }
