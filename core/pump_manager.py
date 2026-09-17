import sqlite3
import json
from typing import List, Dict, Optional
from datetime import datetime
from models.schemas import StationPumpData
from core.config import logger
import os

class PumpManager:
    """
    Gestionnaire des pompes avec base de données SQLite
    Permet de stocker et gérer les informations des pompes indépendamment d'Odoo
    """
    
    def __init__(self, db_path: str = "pump_data.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialiser la base de données SQLite avec les tables nécessaires"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table pour les pompes de session (données d'ouverture)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pump_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                pos_id INTEGER NOT NULL,
                pump_external_id TEXT NOT NULL,
                pump_name TEXT NOT NULL,
                station_id TEXT,
                fuel_type TEXT,
                product_id INTEGER,
                product_name TEXT,
                start_index REAL NOT NULL,
                current_index REAL NOT NULL,
                pump_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, pump_external_id)
            )
        ''')
        
        # Migration: Ajouter les colonnes product_id et product_name si elles n'existent pas
        try:
            cursor.execute("ALTER TABLE pump_sessions ADD COLUMN product_id INTEGER")
            logger.info("Colonne product_id ajoutée à pump_sessions")
        except sqlite3.OperationalError:
            # La colonne existe déjà
            pass
        
        try:
            cursor.execute("ALTER TABLE pump_sessions ADD COLUMN product_name TEXT")
            logger.info("Colonne product_name ajoutée à pump_sessions")
        except sqlite3.OperationalError:
            # La colonne existe déjà
            pass
        
        # Table pour les ventes par pompe
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pump_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                pump_external_id TEXT NOT NULL,
                order_id INTEGER,
                start_index REAL NOT NULL,
                end_index REAL NOT NULL,
                quantity_sold REAL NOT NULL,
                amount_sold REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id, pump_external_id) 
                REFERENCES pump_sessions(session_id, pump_external_id)
            )
        ''')
        
        # Index pour améliorer les performances
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_pump_sessions_session 
            ON pump_sessions(session_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_pump_sales_session 
            ON pump_sales(session_id)
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Base de données des pompes initialisée : {self.db_path}")
    
    def save_session_pumps(self, session_id: int, pos_id: int, pumps: List[StationPumpData]) -> bool:
        """
        Sauvegarder les pompes lors de l'ouverture de session
        
        Args:
            session_id: ID de la session POS
            pos_id: ID du point de vente
            pumps: Liste des données de pompes
            
        Returns:
            bool: True si succès, False sinon
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Nettoyer les données existantes pour cette session
            cursor.execute('DELETE FROM pump_sessions WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM pump_sales WHERE session_id = ?', (session_id,))
            
            # Sauvegarder chaque pompe
            for pump in pumps:
                pump_data = {
                    'id': pump.id,
                    'name': pump.name,
                    'stationId': pump.stationId,
                    'type': pump.type,
                    'start_index': pump.start_index,
                    'product_id': pump.product_id if hasattr(pump, 'product_id') else None,
                    'product_name': pump.product_name if hasattr(pump, 'product_name') else None,
                    'created_at': datetime.now().isoformat()
                }
                
                cursor.execute('''
                    INSERT INTO pump_sessions 
                    (session_id, pos_id, pump_external_id, pump_name, station_id, 
                     fuel_type, product_id, product_name, start_index, current_index, pump_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_id, pos_id, pump.id, pump.name, pump.stationId,
                    pump.type, 
                    pump.product_id if hasattr(pump, 'product_id') else None,
                    pump.product_name if hasattr(pump, 'product_name') else None,
                    pump.start_index, pump.start_index, 
                    json.dumps(pump_data)
                ))
                
                logger.info(f"Pompe sauvegardée: {pump.name} (ID: {pump.id}) - Index: {pump.start_index}")
            
            conn.commit()
            conn.close()
            
            logger.info(f"Session {session_id}: {len(pumps)} pompes sauvegardées")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde des pompes pour session {session_id}: {e}")
            return False
    
    def get_session_pumps(self, session_id: int) -> List[Dict]:
        """
        Récupérer les pompes disponibles pour une session
        
        Args:
            session_id: ID de la session POS
            
        Returns:
            List[Dict]: Liste des pompes avec leurs données actuelles
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT pump_external_id, pump_name, station_id, fuel_type, 
                       start_index, current_index, pump_data, product_id, product_name
                FROM pump_sessions 
                WHERE session_id = ? 
                ORDER BY pump_name
            ''', (session_id,))
            
            results = cursor.fetchall()
            conn.close()
            
            pumps = []
            for result in results:
                pump_info = {
                    'id': result[0],
                    'name': result[1],
                    'stationId': result[2],
                    'type': result[3],
                    'start_index': result[4],
                    'current_index': result[5],
                    'raw_data': json.loads(result[6]) if result[6] else {},
                    'product_id': result[7],
                    'product_name': result[8],
                    'available': True,
                    'quantity_available': result[5] - result[4]  # Index actuel - index début
                }
                pumps.append(pump_info)
            
            logger.debug(f"Session {session_id}: {len(pumps)} pompes récupérées")
            return pumps
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des pompes pour session {session_id}: {e}")
            return []
    
    def get_available_pumps_for_sale(self, session_id: int, min_quantity: float = 0.1) -> List[Dict]:
        """
        Récupérer les pompes disponibles pour la vente (avec carburant)
        
        Args:
            session_id: ID de la session POS
            min_quantity: Quantité minimum disponible pour considérer la pompe comme disponible
            
        Returns:
            List[Dict]: Liste des pompes disponibles pour la vente
        """
        pumps = self.get_session_pumps(session_id)
        available_pumps = []
        
        for pump in pumps:
            if pump['quantity_available'] >= min_quantity:
                pump['status'] = 'available'
                available_pumps.append(pump)
            else:
                pump['status'] = 'empty'
                logger.warning(f"Pompe {pump['name']} vide ou presque vide: {pump['quantity_available']:.2f}L")
        
        return available_pumps
    
    def update_pump_index(self, session_id: int, pump_id: str, new_index: float, order_id: Optional[int] = None) -> bool:
        """
        Mettre à jour l'index d'une pompe après une vente
        
        Args:
            session_id: ID de la session POS
            pump_id: ID externe de la pompe
            new_index: Nouvel index de la pompe
            order_id: ID de la commande (optionnel)
            
        Returns:
            bool: True si succès, False sinon
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Récupérer l'index actuel
            cursor.execute('''
                SELECT current_index FROM pump_sessions 
                WHERE session_id = ? AND pump_external_id = ?
            ''', (session_id, pump_id))
            
            result = cursor.fetchone()
            if not result:
                logger.error(f"Pompe {pump_id} non trouvée pour session {session_id}")
                return False
            
            old_index = result[0]
            quantity_sold = new_index - old_index
            
            if quantity_sold < 0:
                logger.warning(f"Index décroissant détecté pour pompe {pump_id}: {old_index} -> {new_index}")
            
            # Mettre à jour l'index
            cursor.execute('''
                UPDATE pump_sessions 
                SET current_index = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ? AND pump_external_id = ?
            ''', (new_index, session_id, pump_id))
            
            # Enregistrer la vente si il y a eu consommation
            if quantity_sold > 0:
                cursor.execute('''
                    INSERT INTO pump_sales 
                    (session_id, pump_external_id, order_id, start_index, end_index, quantity_sold)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (session_id, pump_id, order_id, old_index, new_index, quantity_sold))
                
                logger.info(f"Vente enregistrée - Pompe {pump_id}: {quantity_sold:.2f}L (Order: {order_id})")
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour de l'index pompe {pump_id}: {e}")
            return False
    
    def get_session_sales_summary(self, session_id: int) -> Dict:
        """
        Récupérer un résumé des ventes par pompe pour une session
        
        Args:
            session_id: ID de la session POS
            
        Returns:
            Dict: Résumé des ventes avec totaux par pompe et global
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Récupérer les ventes par pompe
            cursor.execute('''
                SELECT 
                    ps.pump_external_id,
                    ps.pump_name,
                    ps.fuel_type,
                    ps.start_index,
                    ps.current_index,
                    COALESCE(SUM(sales.quantity_sold), 0) as total_sold,
                    COUNT(sales.id) as nb_sales
                FROM pump_sessions ps
                LEFT JOIN pump_sales sales ON ps.session_id = sales.session_id 
                    AND ps.pump_external_id = sales.pump_external_id
                WHERE ps.session_id = ?
                GROUP BY ps.pump_external_id, ps.pump_name, ps.fuel_type, ps.start_index, ps.current_index
                ORDER BY ps.pump_name
            ''', (session_id,))
            
            results = cursor.fetchall()
            conn.close()
            
            pumps_summary = []
            total_quantity = 0
            total_sales = 0
            
            for result in results:
                pump_data = {
                    'pump_id': result[0],
                    'pump_name': result[1],
                    'fuel_type': result[2],
                    'start_index': result[3],
                    'current_index': result[4],
                    'total_sold': result[5],
                    'nb_sales': result[6],
                    'remaining': result[4] - result[3] - result[5]
                }
                pumps_summary.append(pump_data)
                total_quantity += result[5]
                total_sales += result[6]
            
            summary = {
                'session_id': session_id,
                'pumps': pumps_summary,
                'totals': {
                    'total_quantity_sold': total_quantity,
                    'total_nb_sales': total_sales,
                    'nb_pumps': len(pumps_summary)
                }
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Erreur lors du calcul du résumé pour session {session_id}: {e}")
            return {}
    
    def validate_session_closure(self, session_id: int) -> Dict:
        """
        Valider la cohérence des données avant fermeture de session
        
        Args:
            session_id: ID de la session POS
            
        Returns:
            Dict: Rapport de validation avec erreurs éventuelles
        """
        try:
            summary = self.get_session_sales_summary(session_id)
            validation_report = {
                'valid': True,
                'errors': [],
                'warnings': [],
                'summary': summary
            }
            
            for pump in summary.get('pumps', []):
                pump_id = pump['pump_id']
                pump_name = pump['pump_name']
                
                # Vérifier les index cohérents
                if pump['current_index'] < pump['start_index']:
                    validation_report['errors'].append(
                        f"Pompe {pump_name}: Index final ({pump['current_index']}) < Index initial ({pump['start_index']})"
                    )
                    validation_report['valid'] = False
                
                # Vérifier les quantités cohérentes
                calculated_consumed = pump['current_index'] - pump['start_index']
                if abs(calculated_consumed - pump['total_sold']) > 0.01:  # Tolérance de 0.01L
                    validation_report['warnings'].append(
                        f"Pompe {pump_name}: Écart entre consommation calculée ({calculated_consumed:.2f}L) et ventes ({pump['total_sold']:.2f}L)"
                    )
                
                # Vérifier qu'il n'y a pas de carburant restant significatif
                if pump['remaining'] > 1.0:  # Plus d'1L restant
                    validation_report['warnings'].append(
                        f"Pompe {pump_name}: {pump['remaining']:.2f}L de carburant restant non vendu"
                    )
            
            return validation_report
            
        except Exception as e:
            logger.error(f"Erreur lors de la validation de session {session_id}: {e}")
            return {
                'valid': False,
                'errors': [f"Erreur de validation: {str(e)}"],
                'warnings': [],
                'summary': {}
            }
    
    def cleanup_old_sessions(self, days_old: int = 30) -> int:
        """
        Nettoyer les données de sessions anciennes
        
        Args:
            days_old: Nombre de jours après lesquels supprimer les données
            
        Returns:
            int: Nombre de sessions supprimées
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Supprimer les sessions anciennes
            cursor.execute('''
                DELETE FROM pump_sessions 
                WHERE created_at < datetime('now', '-{} days')
            '''.format(days_old))
            
            deleted_sessions = cursor.rowcount
            
            # Supprimer les ventes orphelines
            cursor.execute('''
                DELETE FROM pump_sales 
                WHERE created_at < datetime('now', '-{} days')
            '''.format(days_old))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Nettoyage effectué: {deleted_sessions} sessions supprimées")
            return deleted_sessions
            
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage: {e}")
            return 0

# Instance globale du gestionnaire de pompes
pump_manager = PumpManager()
