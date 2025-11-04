import xmlrpc.client
import time
from core.config import ODOO_CONFIG, logger

class OdooClient:
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
        self._authenticate()
    
    def _authenticate(self):
        """Authentification avec Odoo"""
        max_retries = 3
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                logger.info(f"Tentative de connexion à Odoo ({retry_count+1}/{max_retries}): URL={self.url}, DB={self.db}, USER={self.username}")
                common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
                
                # Tentative d'authentification avec la clé API (ou mot de passe)
                self.uid = common.authenticate(self.db, self.username, self.api_key, {})
                
                if self.uid:
                    logger.info(f"Authentifié avec Odoo - UID: {self.uid}")
                    return
                else:
                    logger.error("Échec de l'authentification Odoo: identifiants incorrects")
                    raise Exception("Identifiants Odoo incorrects")
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Échec de la tentative {retry_count+1}: {last_error}")
                retry_count += 1
                # Petite pause avant de réessayer
                time.sleep(1)
        
        # Si on arrive ici, toutes les tentatives ont échoué
        logger.error(f"Échec de l'authentification Odoo après {max_retries} tentatives: {last_error}")
        raise Exception(f"Échec de l'authentification Odoo: {last_error}")
    
    def execute_kw(self, model: str, method: str, args: list, kwargs: dict = None):
        """Exécute une méthode Odoo"""
        kwargs = kwargs or {}
        max_retries = 2
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                # Vérifier si l'authentification est valide
                if not self.uid:
                    logger.warning("UID non valide, tentative de réauthentification...")
                    self._authenticate()
                
                models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
                result = models.execute_kw(self.db, self.uid, self.api_key, model, method, args, kwargs)
                return result
                
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                logger.warning(f"Erreur lors de l'exécution de {method} sur {model} (tentative {retry_count}/{max_retries}): {last_error}")
                
                # Si c'est un problème d'authentification, on réessaie de s'authentifier
                if "session expired" in last_error.lower() or "access denied" in last_error.lower():
                    try:
                        logger.info("Tentative de réauthentification...")
                        self._authenticate()
                    except Exception as auth_error:
                        logger.error(f"Échec de réauthentification: {auth_error}")
                
                # Petite pause avant de réessayer
                if retry_count < max_retries:
                    time.sleep(1)
        
        # Si on arrive ici, toutes les tentatives ont échoué
        logger.error(f"Échec de l'exécution de {method} sur {model} après {max_retries} tentatives: {last_error}")
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
