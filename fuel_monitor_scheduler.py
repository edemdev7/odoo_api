"""
Script de surveillance automatique des comptes fuel

Ce script utilise APScheduler pour vérifier périodiquement
les changements de crédit et envoyer les webhooks automatiquement.

Usage:
    python fuel_monitor_scheduler.py

Configuration:
    - Définir JWT_TOKEN avec votre token d'authentification
    - Ajuster CHECK_INTERVAL_SECONDS selon vos besoins
"""

import os
import sys
import time
import logging
import requests
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fuel_monitor.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# ===== CONFIGURATION =====
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001")
JWT_TOKEN = os.getenv("JWT_TOKEN", "YOUR_JWT_TOKEN_HERE")  # À remplacer
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "120"))  # 2 minutes par défaut

# En-têtes HTTP
HEADERS = {
    "Authorization": f"Bearer {JWT_TOKEN}",
    "Content-Type": "application/json"
}


def initialize_cache():
    """Initialiser le cache au démarrage"""
    try:
        logger.info("🔧 Initialisation du cache...")
        
        response = requests.post(
            f"{API_BASE_URL}/fuel-monitor/initialize-cache",
            headers=HEADERS,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Cache initialisé avec {data.get('count', 0)} partenaires")
        else:
            logger.error(f"❌ Erreur initialisation cache: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"❌ Exception lors de l'initialisation: {e}")


def check_credit_changes():
    """Vérifier les changements de crédit"""
    try:
        logger.info(f"🔍 Vérification des changements de crédit...")
        
        response = requests.get(
            f"{API_BASE_URL}/fuel-monitor/check-credit-changes",
            headers=HEADERS,
            params={"since_minutes": CHECK_INTERVAL_SECONDS // 60 + 1},
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            changes_count = data.get('count', 0)
            
            if changes_count > 0:
                logger.info(f"💰 {changes_count} changement(s) détecté(s)")
                
                # Afficher les détails
                changes = data.get('data', {}).get('changes_detected', [])
                for change in changes:
                    logger.info(
                        f"  → {change.get('partner_name')} (ID: {change.get('partner_id')}): "
                        f"+{change.get('amount_added', 0):.2f} CFA"
                    )
            else:
                logger.info("✓ Aucun changement détecté")
                
        else:
            logger.error(f"❌ Erreur API: {response.status_code} - {response.text}")
            
    except requests.exceptions.Timeout:
        logger.error("⏱️ Timeout lors de la vérification")
    except Exception as e:
        logger.error(f"❌ Exception lors de la vérification: {e}")


def get_cache_status():
    """Afficher l'état du cache (pour monitoring)"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/fuel-monitor/cache-status",
            headers=HEADERS,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"📊 Cache status: {data.get('count', 0)} partenaires surveillés")
        else:
            logger.warning(f"⚠️ Impossible de récupérer le status du cache: {response.status_code}")
            
    except Exception as e:
        logger.warning(f"⚠️ Exception lors de la récupération du status: {e}")


def health_check():
    """Vérifier que l'API est accessible"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/health",
            timeout=5
        )
        
        if response.status_code == 200:
            logger.info("✅ API accessible")
            return True
        else:
            logger.error(f"❌ API non accessible: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ API inaccessible: {e}")
        return False


def main():
    """Point d'entrée principal"""
    logger.info("=" * 60)
    logger.info("🚀 Démarrage du moniteur de comptes fuel")
    logger.info(f"   API: {API_BASE_URL}")
    logger.info(f"   Intervalle: {CHECK_INTERVAL_SECONDS} secondes")
    logger.info("=" * 60)
    
    # Vérifier la configuration
    if JWT_TOKEN == "YOUR_JWT_TOKEN_HERE":
        logger.error("❌ JWT_TOKEN non configuré ! Définissez la variable d'environnement JWT_TOKEN")
        sys.exit(1)
    
    # Health check
    if not health_check():
        logger.error("❌ API non accessible. Arrêt du programme.")
        sys.exit(1)
    
    # Initialiser le cache
    initialize_cache()
    
    # Afficher le status initial
    get_cache_status()
    
    # Créer le scheduler
    scheduler = BlockingScheduler()
    
    # Ajouter la tâche de vérification périodique
    scheduler.add_job(
        check_credit_changes,
        trigger=IntervalTrigger(seconds=CHECK_INTERVAL_SECONDS),
        id='check_credit_changes',
        name='Vérification des changements de crédit',
        replace_existing=True
    )
    
    # Ajouter une tâche de monitoring toutes les 10 minutes
    scheduler.add_job(
        get_cache_status,
        trigger=IntervalTrigger(minutes=10),
        id='cache_status',
        name='Monitoring du cache',
        replace_existing=True
    )
    
    # Ajouter un health check toutes les 5 minutes
    scheduler.add_job(
        health_check,
        trigger=IntervalTrigger(minutes=5),
        id='health_check',
        name='Health check API',
        replace_existing=True
    )
    
    logger.info("✅ Scheduler configuré")
    logger.info(f"   - Vérification crédit: toutes les {CHECK_INTERVAL_SECONDS}s")
    logger.info(f"   - Monitoring cache: toutes les 10 min")
    logger.info(f"   - Health check: toutes les 5 min")
    
    try:
        logger.info("🔄 Démarrage de la surveillance...")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Arrêt du moniteur demandé")
        scheduler.shutdown()
        logger.info("👋 Moniteur arrêté proprement")


if __name__ == "__main__":
    main()
