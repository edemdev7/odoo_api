/**
 * API Client pour la récupération des pompes d'une session POS
 * 
 * Usage:
 * 
 * import { PosApiClient } from './pos-api-client';
 * 
 * const client = new PosApiClient('http://localhost:8002');
 * await client.login('user', 'password');
 * 
 * const pumps = await client.getSessionPumps(1, 123);
 * console.log(pumps);
 */

// Types TypeScript
interface Pump {
  id: string;
  name: string;
  stationId: string;
  type: string;
  start_index: number;
  current_index: number;
  quantity_available: number;
  available: boolean;
  product_id: number;
  product_name: string;
  raw_data: Record<string, any>;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  count?: number;
  message?: string;
}

interface SessionStatus {
  has_active_session: boolean;
  session_id?: number;
  session_state?: string;
  can_open?: boolean;
  pos_id?: number;
  pos_name?: string;
}

class PosApiClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string = 'http://localhost:8002') {
    this.baseUrl = baseUrl;
  }

  /**
   * Authentification
   */
  async login(username: string, password: string): Promise<string> {
    const response = await fetch(`${this.baseUrl}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      throw new Error(`Erreur d'authentification: ${response.status}`);
    }

    const data = await response.json();
    this.token = data.access_token;
    return this.token;
  }

  /**
   * Headers avec authentification
   */
  private getHeaders(): HeadersInit {
    if (!this.token) {
      throw new Error('Non authentifié. Appelez login() d\'abord.');
    }

    return {
      'Authorization': `Bearer ${this.token}`,
      'Content-Type': 'application/json',
    };
  }

  /**
   * Récupérer le statut de la session active
   */
  async getSessionStatus(posId: number): Promise<SessionStatus> {
    const response = await fetch(
      `${this.baseUrl}/pos/${posId}/session-status`,
      {
        headers: this.getHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(`Erreur statut session: ${response.status}`);
    }

    return await response.json();
  }

  /**
   * Récupérer toutes les pompes d'une session
   */
  async getSessionPumps(posId: number, sessionId: number): Promise<Pump[]> {
    const response = await fetch(
      `${this.baseUrl}/pos/${posId}/session/${sessionId}/pumps`,
      {
        headers: this.getHeaders(),
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || `Erreur: ${response.status}`);
    }

    const result: ApiResponse<Pump[]> = await response.json();
    
    if (!result.success) {
      throw new Error('Erreur lors de la récupération des pompes');
    }

    return result.data;
  }

  /**
   * Récupérer les pompes de la session active
   */
  async getActivePumps(posId: number): Promise<Pump[]> {
    // 1. Récupérer la session active
    const status = await this.getSessionStatus(posId);

    if (!status.has_active_session || !status.session_id) {
      throw new Error('Aucune session active');
    }

    // 2. Récupérer les pompes
    return await this.getSessionPumps(posId, status.session_id);
  }

  /**
   * Récupérer une pompe spécifique par son ID
   */
  async getPumpById(
    posId: number,
    sessionId: number,
    pumpId: string
  ): Promise<Pump | undefined> {
    const pumps = await this.getSessionPumps(posId, sessionId);
    return pumps.find(p => p.id === pumpId);
  }

  /**
   * Filtrer les pompes par type de carburant
   */
  async getPumpsByFuelType(
    posId: number,
    sessionId: number,
    fuelType: string
  ): Promise<Pump[]> {
    const pumps = await this.getSessionPumps(posId, sessionId);
    return pumps.filter(p => p.type === fuelType);
  }

  /**
   * Calculer le total vendu par pompe
   */
  async getTotalSoldByPump(
    posId: number,
    sessionId: number
  ): Promise<Map<string, number>> {
    const pumps = await this.getSessionPumps(posId, sessionId);
    const totals = new Map<string, number>();

    pumps.forEach(pump => {
      totals.set(pump.id, pump.quantity_available);
    });

    return totals;
  }

  /**
   * Calculer le total vendu par type de carburant
   */
  async getTotalSoldByFuelType(
    posId: number,
    sessionId: number
  ): Promise<Map<string, { count: number; total: number }>> {
    const pumps = await this.getSessionPumps(posId, sessionId);
    const totals = new Map<string, { count: number; total: number }>();

    pumps.forEach(pump => {
      const existing = totals.get(pump.type) || { count: 0, total: 0 };
      totals.set(pump.type, {
        count: existing.count + 1,
        total: existing.total + pump.quantity_available,
      });
    });

    return totals;
  }
}

// ============================================
// Exemples d'utilisation
// ============================================

/**
 * Exemple 1: Récupération simple
 */
async function exemple1() {
  const client = new PosApiClient();
  
  try {
    // Authentification
    await client.login('user', 'password');
    console.log('✅ Authentifié');

    // Récupérer les pompes
    const pumps = await client.getSessionPumps(1, 123);
    
    console.log(`\n📊 ${pumps.length} pompe(s) trouvée(s):`);
    pumps.forEach(pump => {
      console.log(`  - ${pump.name}: ${pump.quantity_available}L vendus`);
    });
  } catch (error) {
    console.error('❌ Erreur:', error);
  }
}

/**
 * Exemple 2: Récupération automatique de la session active
 */
async function exemple2() {
  const client = new PosApiClient();
  
  try {
    await client.login('user', 'password');
    
    // Récupérer directement les pompes de la session active
    const pumps = await client.getActivePumps(1);
    
    console.log(`\n⛽ Pompes actives:`);
    pumps.forEach(pump => {
      console.log(`  ${pump.name} (${pump.type}): ${pump.current_index}L`);
    });
  } catch (error) {
    console.error('❌ Erreur:', error);
  }
}

/**
 * Exemple 3: Filtrage et calculs
 */
async function exemple3() {
  const client = new PosApiClient();
  
  try {
    await client.login('user', 'password');
    
    const posId = 1;
    const sessionId = 123;
    
    // 1. Pompes essence uniquement
    const petrolPumps = await client.getPumpsByFuelType(posId, sessionId, 'PETROL');
    console.log(`\n⛽ ${petrolPumps.length} pompe(s) essence`);
    
    // 2. Total vendu par type
    const totalsByType = await client.getTotalSoldByFuelType(posId, sessionId);
    
    console.log('\n📊 Ventes par type:');
    totalsByType.forEach((stats, type) => {
      console.log(`  ${type}: ${stats.count} pompe(s), ${stats.total.toFixed(2)}L`);
    });
    
    // 3. Chercher une pompe spécifique
    const pump001 = await client.getPumpById(posId, sessionId, 'pump_001');
    if (pump001) {
      console.log(`\n🔍 Pompe pump_001:`);
      console.log(`  Index: ${pump001.start_index} → ${pump001.current_index}`);
      console.log(`  Vendu: ${pump001.quantity_available}L`);
    }
  } catch (error) {
    console.error('❌ Erreur:', error);
  }
}

/**
 * Exemple 4: Interface React
 */
function PumpsDisplay() {
  const [pumps, setPumps] = React.useState<Pump[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    async function loadPumps() {
      const client = new PosApiClient();
      
      try {
        await client.login('user', 'password');
        const data = await client.getActivePumps(1);
        setPumps(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Erreur inconnue');
      } finally {
        setLoading(false);
      }
    }

    loadPumps();
  }, []);

  if (loading) return <div>Chargement...</div>;
  if (error) return <div>Erreur: {error}</div>;

  return (
    <div className="pumps-container">
      <h2>Pompes actives ({pumps.length})</h2>
      {pumps.map(pump => (
        <div key={pump.id} className="pump-card">
          <h3>{pump.name}</h3>
          <p>Type: {pump.type}</p>
          <p>Produit: {pump.product_name}</p>
          <p>Index: {pump.start_index} → {pump.current_index} L</p>
          <p className="highlight">
            Vendu: {pump.quantity_available.toFixed(2)} L
          </p>
        </div>
      ))}
    </div>
  );
}

/**
 * Exemple 5: Mise à jour en temps réel
 */
async function exemple5() {
  const client = new PosApiClient();
  await client.login('user', 'password');

  // Polling toutes les 30 secondes
  setInterval(async () => {
    try {
      const pumps = await client.getActivePumps(1);
      
      console.log('\n🔄 Mise à jour:', new Date().toLocaleTimeString());
      pumps.forEach(pump => {
        console.log(`  ${pump.name}: ${pump.current_index}L`);
      });
    } catch (error) {
      console.error('❌ Erreur lors de la mise à jour:', error);
    }
  }, 30000);
}

// Export pour utilisation en module
export { PosApiClient, Pump, ApiResponse, SessionStatus };
export default PosApiClient;
