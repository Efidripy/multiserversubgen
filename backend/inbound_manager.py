"""
Модуль управления инбаундами node panel
Содержит функции для получения, создания, клонирования и удаления инбаундов
"""
import requests
import json
import logging
from typing import List, Dict, Optional

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
                    inbound = {
                        "id": ib.get("id"),
                        "node_name": node["name"],
                        "node_ip": node["ip"],
                        "protocol": ib.get("protocol"),
                        "port": ib.get("port"),
                        "remark": ib.get("remark", ""),
                        "enable": ib.get("enable", True),
                        "streamSettings": ib.get("streamSettings", {}),
                        "settings": ib.get("settings", {})
                    }
                    security = ib.get("streamSettings", {}).get("security", "")
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
            s.post(f"{base_url}/login", data={"username": node['user'], "password": self.decrypt(node.get('password', ''))})
            res = s.get(f"{base_url}/panel/api/inbounds/list", timeout=5)
            if res.status_code == 200:
                data = res.json()
                return data.get("obj", []) if data.get("success", False) else []
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
            s.post(f"{base_url}/login", 
                  data={"username": node['user'], "password": self.decrypt(node.get('password', ''))})
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
            s.post(f"{base_url}/login", 
                  data={"username": node['user'], "password": self.decrypt(node.get('password', ''))})
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
            s.post(f"{base_url}/login", 
                  data={"username": node['user'], "password": self.decrypt(node.get('password', ''))})
            res = s.post(f"{base_url}/panel/api/inbounds/resetClientTraffic/{inbound_id}", 
                        timeout=5)
            return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to reset inbound traffic: {exc}")
            return False