import xmlrpc.client
import time
from datetime import datetime, timedelta
from core.config import ODOO_CONFIG, logger

class OdooClient:
    # Cache des erreurs récentes pour éviter de spam les logs
    _last_error_time = {}
    _error_cache_duration = 60  # secondes
    
    def __init__(self, custom_config=None):
        """
        Initialise le client Odoo
        :param custom_config: Configuration personnalisée (optionnel) avec url, db, username, api_key
        """
        config = ODOO_CONFIG.copy()
        if custom_config:
            for key, value in custom_config.items():
                if value:  # Ne remplacer que si la valeur n'est pas None
                    config[key] = value
                    
        self.url = config["url"]
        self.db = config["db"]
        self.username = config["username"]
        self.api_key = config["api_key"]
        self.uid = None
        self._authenticated = False  # Flag pour lazy authentication
        self._cache_key = f"{self.url}_{self.db}"
    
    def _should_log_error(self):
        """Vérifie si on doit logger l'erreur (évite le spam)"""
        now = datetime.now()
        if self._cache_key in self._last_error_time:
            last_error = self._last_error_time[self._cache_key]
            if (now - last_error).total_seconds() < self._error_cache_duration:
                return False  # Ne pas logger, trop récent
        
        self._last_error_time[self._cache_key] = now
        return True
    
    def _authenticate(self):
        """Authentification avec Odoo (lazy - appelée seulement quand nécessaire)"""
        if self._authenticated and self.uid:
            return  # Déjà authentifié
            
        max_retries = 2  # Réduit de 3 à 2
        retry_count = 0
        last_error = None
        first_attempt = True
        
        while retry_count < max_retries:
            try:
                # Logger seulement la première tentative pour réduire le spam
                if first_attempt:
                    logger.info(f"Connexion à Odoo: {self.url} / {self.db}")
                    first_attempt = False
                
                common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common', allow_none=True)
                
                # Tentative d'authentification avec la clé API (ou mot de passe)
                self.uid = common.authenticate(self.db, self.username, self.api_key, {})
                
                if self.uid:
                    logger.info(f"✅ Authentifié sur {self.db} - UID: {self.uid}")
                    self._authenticated = True
                    return
                else:
                    raise Exception("Identifiants Odoo incorrects")
                    
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                
                # Ne logger que si on n'a pas déjà loggé récemment
                if self._should_log_error():
                    if "523" in last_error or "Origin Is Unreachable" in last_error:
                        logger.error(f"❌ Serveur Odoo inaccessible ({self.url}) - Vérifiez que le serveur est en ligne")
                    else:
                        logger.warning(f"Échec connexion Odoo ({retry_count}/{max_retries}): {last_error}")
                
                # Pause courte avant retry
                if retry_count < max_retries:
                    time.sleep(0.5)
        
        # Si on arrive ici, toutes les tentatives ont échoué
        if "523" in last_error or "Origin Is Unreachable" in last_error:
            raise Exception(f"Serveur Odoo inaccessible. Le serveur {self.url} ne répond pas (erreur 523).")
        else:
            raise Exception(f"Échec de l'authentification Odoo: {last_error}")
    
    def execute_kw(self, model: str, method: str, args: list, kwargs: dict = None):
        """Exécute une méthode Odoo"""
        kwargs = kwargs or {}
        max_retries = 1  # Réduit à 1 retry
        retry_count = 0
        last_error = None
        
        while retry_count <= max_retries:
            try:
                # S'authentifier si ce n'est pas déjà fait (lazy authentication)
                if not self._authenticated or not self.uid:
                    if self._should_log_error():
                        logger.info(f"Authentification sur {self.db}...")
                    self._authenticate()
                
                models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object', allow_none=True)
                result = models.execute_kw(self.db, self.uid, self.api_key, model, method, args, kwargs)
                return result
                
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                
                # Logger avec modération
                if self._should_log_error():
                    if "523" in last_error or "Origin Is Unreachable" in last_error:
                        logger.error(f"❌ Serveur Odoo inaccessible: {self.url}")
                    else:
                        logger.warning(f"Erreur {method} sur {model}: {last_error[:100]}")
                
                # Si c'est un problème d'authentification, on réessaie de s'authentifier
                if retry_count <= max_retries and ("session expired" in last_error.lower() or "access denied" in last_error.lower()):
                    self._authenticated = False
                    time.sleep(0.3)
                else:
                    break
        
        # Si on arrive ici, échec
        if "523" in last_error or "Origin Is Unreachable" in last_error:
            raise Exception(f"Serveur Odoo inaccessible ({self.url})")
        else:
            raise Exception(f"Erreur Odoo: {last_error}")

# Instance globale du client Odoo par défaut
default_odoo_client = OdooClient()

# Fonction pour obtenir le client Odoo approprié pour l'utilisateur
def get_odoo_client(user=None):
    """
    Renvoie le client Odoo approprié en fonction de l'utilisateur et de sa base de données authentifiée
    
    :param user: Utilisateur authentifié (avec odoo_db dans le token JWT)
    :return: Instance de OdooClient configurée pour la bonne base de données
    """
    from core.security import get_odoo_config_from_user
    
    if user:
        try:
            # Récupérer la configuration de la base de données depuis le token de l'utilisateur
            db_config = get_odoo_config_from_user(user)
            
            if db_config:
                # Créer un client Odoo avec la configuration de la base authentifiée
                logger.debug(f"Création du client Odoo pour la base: {db_config['name']}")
                return OdooClient(custom_config={
                    'url': db_config['url'],
                    'db': db_config['db'],
                    'username': db_config['username'],
                    'api_key': db_config['api_key']
                })
            else:
                logger.warning(f"Configuration Odoo non trouvée pour l'utilisateur, utilisation de la base par défaut")
                
        except Exception as e:
            logger.error(f"Erreur lors de la création du client Odoo pour l'utilisateur: {e}")
            # En cas d'erreur, utiliser le client par défaut
    
    # Utiliser le client par défaut si pas d'utilisateur ou erreur
    logger.debug("Utilisation du client Odoo par défaut")
    return default_odoo_client
