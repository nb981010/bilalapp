# Bilal App Architecture Recommendation


## 1. **Core Architecture Pattern: Microservices with Event-Driven Design**

```
┌─────────────────────────────────────────────────────────┐
│                     Load Balancer/Nginx                  │
└─────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Frontend   │  │   Backend    │  │    Main      │
│   Service    │  │   Service    │  │   Service    │
│  (React/Vue) │  │  (FastAPI)   │  │  (Scheduler) │
└──────────────┘  └──────────────┘  └──────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
                  ┌─────────────────┐
                  │   PostgreSQL    │
                  │   + TimescaleDB │
                  └─────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│    Redis     │  │   Message    │  │   Logging    │
│   (Cache)    │  │   Queue      │  │  (ELK/Loki)  │
└──────────────┘  └──────────────┘  └──────────────┘
```

---

## 2. **Critical Components Breakdown**

### **A. Main Service (Scheduler Engine)** - *The Heart*
```python
Responsibilities:
├── Azan Schedule Calculation (Primary + Fallback)
├── Job Queue Management (APScheduler/Celery)
├── Playback Orchestration
├── Watchdog & Health Checks
└── State Machine for Playback

Key Requirements:
- Run as systemd service with auto-restart
- Heartbeat every 30 seconds to DB
- Idempotent job execution (prevent duplicates)
- Graceful shutdown handling
```

**Recommended Stack:**
- **APScheduler** with PostgreSQL job store (persistent)
- **State Machine:** Use `python-statemachine` for playback states
- **Watchdog:** Separate thread monitoring job execution

### **B. Backend Service (API Layer)**
```python
Responsibilities:
├── RESTful API for Frontend
├── Settings CRUD (Production vs Test DB)
├── Audio System Discovery & Control
├── Authentication (4-digit PIN)
└── Real-time Status WebSocket

Endpoints:
├── /api/v1/dashboard/status
├── /api/v1/schedule/today
├── /api/v1/settings/* (Protected)
├── /api/v1/test/* (Test DB only)
├── /api/v1/audio/discover
└── /ws/status (WebSocket)
```

**Recommended Stack:**
- **FastAPI** (async, high performance)
- **SQLAlchemy 2.0** with async support
- **Pydantic** for validation
- **JWT** for session management

### **C. Frontend Service**
```javascript
Responsibilities:
├── Dashboard (Real-time Status)
├── Settings UI (PIN Protected)
├── Testing UI (Isolated Test DB)
└── Schedule History Viewer

Key Features:
- Polling every 30s (only when tab active)
- WebSocket for instant updates
- Color-coded job status
- Manual refresh button
```

**Recommended Stack:**
- **React** or **Vue 3** with TypeScript
- **TanStack Query** for data fetching
- **Zustand/Pinia** for state management
- **Tailwind CSS** for styling

---

## 3. **Database Schema Design**

### **Production Database:**
```sql
-- Settings Table
CREATE TABLE settings (
    id SERIAL PRIMARY KEY,
    location VARCHAR(100) DEFAULT 'Dubai',
    calc_method VARCHAR(50) DEFAULT 'IACAD',
    asr_madhab VARCHAR(50) DEFAULT 'Standard',
    css_mode VARCHAR(20) DEFAULT 'online', -- online/offline
    azan_calc_mode VARCHAR(20) DEFAULT 'online',
    sonos_mode VARCHAR(20) DEFAULT 'online',
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audio Systems Table
CREATE TABLE audio_systems (
    id SERIAL PRIMARY KEY,
    system_type VARCHAR(20), -- onboard/sonos/toa
    zone_name VARCHAR(100),
    zone_id VARCHAR(100),
    enabled BOOLEAN DEFAULT false,
    api_mode VARCHAR(20), -- online/offline/n/a
    discovered_at TIMESTAMP,
    last_seen TIMESTAMP
);

-- Schedule Table
CREATE TABLE prayer_schedule (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    prayer_name VARCHAR(20), -- Fajr/Dhuhr/Asr/Maghrib/Isha
    scheduled_time TIMESTAMP NOT NULL,
    calculation_method VARCHAR(50),
    source VARCHAR(20), -- api/offline/imported
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(date, prayer_name)
);

-- Job Execution History
CREATE TABLE job_history (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(100) UNIQUE,
    prayer_name VARCHAR(20),
    scheduled_time TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(20), -- scheduled/running/completed/failed
    audio_system VARCHAR(20),
    playback_duration INTEGER, -- seconds
    expected_duration INTEGER,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Service Health Table
CREATE TABLE service_health (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(50),
    status VARCHAR(20), -- running/stopped/error
    last_heartbeat TIMESTAMP,
    pid INTEGER,
    error_details TEXT
);

-- Playback State Table (for interruption recovery)
CREATE TABLE playback_state (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(100),
    audio_file VARCHAR(255),
    position_seconds INTEGER,
    audio_system VARCHAR(20),
    interrupted_at TIMESTAMP,
    resumed_at TIMESTAMP
);
```

### **Test Database:**
Identical schema but completely separate instance to prevent any production impact.

---

## 4. **Scheduler Architecture (Critical!)**

### **Calculation Flow:**
```python
┌─────────────────────────────────────────────────┐
│  Daily Calculation Job (12:01 AM)                │
│  ├── Fetch Settings (location, method, madhab)   │
│  ├── Try: Online API (primary)                   │
│  ├── Fallback: Offline Calculation               │
│  ├── Store in prayer_schedule table              │
│  └── Schedule 5 jobs for today's prayers         │
└─────────────────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────┐
│  Azan Playback Job (Exact Prayer Time)           │
│  ├── Check: No duplicate job running             │
│  ├── State: SCHEDULED → RUNNING                  │
│  ├── Discover Active Audio Systems               │
│  ├── Stop Any Active Playback (if exists)        │
│  ├── Start Azan with Watchdog                    │
│  ├── Monitor: Duration, Interruptions            │
│  ├── Handle: Resume if interrupted               │
│  ├── State: RUNNING → COMPLETED/FAILED           │
│  └── Log to job_history                          │
└─────────────────────────────────────────────────┘
```

### **Scheduler Implementation:**
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

jobstores = {
    'default': SQLAlchemyJobStore(url='postgresql://...')
}

executors = {
    'default': ThreadPoolExecutor(10)
}

job_defaults = {
    'coalesce': True,  # Combine missed runs
    'max_instances': 1,  # Prevent duplicate jobs
    'misfire_grace_time': 30  # 30 sec tolerance
}

scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone='Asia/Dubai'
)
```

---

## 5. **Playback State Machine**

```python
from statemachine import StateMachine, State

class AzanPlaybackStateMachine(StateMachine):
    idle = State('Idle', initial=True)
    preparing = State('Preparing')
    playing = State('Playing')
    paused = State('Paused')
    completed = State('Completed')
    failed = State('Failed')
    
    start = idle.to(preparing)
    play = preparing.to(playing)
    pause = playing.to(paused)
    resume = paused.to(playing)
    complete = playing.to(completed)
    fail = (preparing.to(failed) | 
            playing.to(failed) | 
            paused.to(failed))
    
    def on_enter_playing(self):
        # Start watchdog
        # Log playback start
        
    def on_exit_playing(self):
        # Check duration
        # Log playback end
```

---

## 6. **Audio System Architecture**

### **Priority & Fallback Chain:**
```
1. Onboard Audio (Always Available - Default)
   └── No discovery needed
   
2. Sonos System (If Enabled)
   ├── Try: Cloud API (SonosAPI)
   └── Fallback: Local SoCo
   
3. TOA System (If Enabled)
   └── Discovery & Control Logic
```

### **Discovery Service:**
```python
class AudioDiscoveryService:
    async def discover_all(self):
        systems = []
        
        # Always available
        systems.append(OnboardAudio())
        
        # Conditional discovery
        if settings.sonos_enabled:
            sonos_zones = await self.discover_sonos()
            systems.extend(sonos_zones)
            
        if settings.toa_enabled:
            toa_zones = await self.discover_toa()
            systems.extend(toa_zones)
            
        # Store in audio_systems table
        await self.update_database(systems)
        return systems
```

---

## 7. **Watchdog & Monitoring**

### **Multi-Layer Watchdog:**
```python
class AzanWatchdog:
    def __init__(self, job_id, expected_duration):
        self.job_id = job_id
        self.expected_duration = expected_duration
        self.start_time = None
        self.position_tracker = []
        
    async def monitor(self):
        """
        1. Track playback position every 5 seconds
        2. Detect interruptions
        3. Auto-resume if stopped
        4. Alert if duration < 90% of expected
        """
        while self.is_playing():
            position = await self.get_position()
            self.position_tracker.append({
                'timestamp': datetime.now(),
                'position': position
            })
            
            # Detect interruption
            if await self.detect_interruption():
                await self.handle_interruption()
                
            await asyncio.sleep(5)
            
    async def handle_interruption(self):
        """Resume from last known position"""
        last_position = self.position_tracker[-1]['position']
        await self.save_state(last_position)
        await self.stop_other_playback()
        await self.resume_from(last_position)
```

### **Health Check Service:**
```python
# Runs every 30 seconds
async def health_check():
    services = ['main', 'backend', 'scheduler']
    
    for service in services:
        status = await check_service_status(service)
        await db.update_service_health(
            service_name=service,
            status=status,
            last_heartbeat=datetime.now()
        )
        
        if status != 'running':
            await alert_system(f"{service} is down!")
            # Auto-restart logic
            await restart_service(service)
```

---

## 8. **Testing Strategy**

### **Test Database Isolation:**
```python
class DatabaseRouter:
    def route(self, request):
        if '/api/v1/test/' in request.path:
            return 'test_db'
        return 'production_db'
        
# In settings
DATABASES = {
    'production_db': {
        'ENGINE': 'postgresql',
        'NAME': 'bilalapp_prod',
    },
    'test_db': {
        'ENGINE': 'postgresql',
        'NAME': 'bilalapp_test',
    }
}
```

### **CI/CD Checks:**
```yaml
# .github/workflows/ci.yml
name: Bilal App CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check Test UI Isolation
        run: |
          # Ensure test endpoints only touch test DB
          pytest tests/test_database_isolation.py
          
      - name: Scheduler Reliability Tests
        run: |
          pytest tests/test_scheduler_reliability.py
          
      - name: Playback State Machine Tests
        run: |
          pytest tests/test_playback_statemachine.py
```

---

## 9. **Deployment Architecture**

### **Systemd Services:**
```ini
# /etc/systemd/system/bilalapp.main.service
[Unit]
Description=Bilal App Main Service (Scheduler)
After=network.target postgresql.service

[Service]
Type=simple
User=bilalapp
WorkingDirectory=/opt/bilalapp
ExecStart=/opt/bilalapp/venv/bin/python main_service.py
Restart=always
RestartSec=10

# Port conflict prevention
ExecStartPre=/usr/local/bin/check_ports.sh

[Install]
WantedBy=multi-user.target
```

### **Port Conflict Prevention:**
```bash
#!/bin/bash
# check_ports.sh

PORTS=(8000 8001 8002)
APP_NAME="bilalapp"

for port in "${PORTS[@]}"; do
    PID=$(lsof -ti:$port)
    if [ ! -z "$PID" ]; then
        # Check if it's our process
        PROCESS_NAME=$(ps -p $PID -o comm=)
        if [[ $PROCESS_NAME == *"$APP_NAME"* ]]; then
            echo "Killing stale process $PID on port $port"
            kill -9 $PID
        fi
    fi
done
```

---

## 10. **Monitoring & Alerting**

### **Recommended Tools:**
```yaml
Logging:
  - Loki + Grafana (lightweight)
  - OR ELK Stack (full-featured)

Metrics:
  - Prometheus + Grafana
  - Track: Job success rate, latency, system health

Alerting:
  - Alertmanager
  - Trigger on:
    - Scheduler down > 1 min
    - Job failure
    - Playback duration < 90% expected
    - Service heartbeat missed

Monitoring Dashboard:
  - Real-time job status
  - Service health
  - Audio system status
  - Historical trends
```

### **Key Metrics to Track:**
```python
# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge

azan_jobs_total = Counter(
    'azan_jobs_total', 
    'Total azan jobs', 
    ['status']
)

azan_duration = Histogram(
    'azan_playback_duration_seconds',
    'Azan playback duration'
)

scheduler_health = Gauge(
    'scheduler_health',
    'Scheduler health status'
)
```

---

## 11. **Frontend Implementation Details**

### **Dashboard Polling Strategy:**
```javascript
// React example
import { useQuery } from '@tanstack/react-query';

function Dashboard() {
  const { data, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboardData,
    refetchInterval: 30000, // 30 seconds
    refetchIntervalInBackground: false, // Only when tab active
  });
  
  const { data: schedule } = useQuery({
    queryKey: ['schedule'],
    queryFn: fetchTodaySchedule,
    refetchInterval: 300000, // 5 minutes
  });
  
  return (
    <div>
      <TodaySchedule data={schedule} onRefresh={refetch} />
      <SystemStatus data={data} />
    </div>
  );
}
```

### **PIN Protection:**
```javascript
// Settings access control
function SettingsPage() {
  const [isUnlocked, setIsUnlocked] = useState(false);
  
  if (!isUnlocked) {
    return <PinInput onSuccess={() => setIsUnlocked(true)} />;
  }
  
  return <SettingsPanel />;
}

// Backend validation
@app.post("/api/v1/auth/verify-pin")
async def verify_pin(pin: str):
    HARDCODED_PIN = "2234"
    if pin == HARDCODED_PIN:
        token = create_session_token()
        return {"token": token}
    raise HTTPException(401, "Invalid PIN")
```

---

## 12. **Recommended Project Structure**

```
bilalapp/
├── services/
│   ├── main_service/           # Scheduler engine
│   │   ├── scheduler.py
│   │   ├── calculator.py
│   │   ├── playback.py
│   │   ├── watchdog.py
│   │   └── state_machine.py
│   ├── backend_service/        # API layer
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   └── utils/
│   └── frontend_service/       # UI
│       ├── src/
│       ├── components/
│       └── pages/
├── shared/
│   ├── database/
│   │   ├── models.py
│   │   └── migrations/
│   ├── config/
│   └── utils/
├── audio_systems/
│   ├── onboard.py
│   ├── sonos.py
│   └── toa.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── deployment/
│   ├── systemd/
│   ├── nginx/
│   └── docker/
├── monitoring/
│   ├── grafana/
│   └── prometheus/
└── docs/
    ├── api.md
    ├── architecture.md
    └── deployment.md
```

---

## 13. **Critical Implementation Checklist**

### **Phase 1: Foundation (Week 1-2)**
- [ ] Setup PostgreSQL with proper schema
- [ ] Implement database models with SQLAlchemy
- [ ] Create production/test database separation
- [ ] Setup APScheduler with persistent job store
- [ ] Implement basic calculation (online + offline fallback)

### **Phase 2: Core Scheduler (Week 3-4)**
- [ ] Implement daily schedule calculation job
- [ ] Implement azan playback job with state machine
- [ ] Add job deduplication logic
- [ ] Create watchdog service
- [ ] Implement interruption recovery

### **Phase 3: Audio Systems (Week 5-6)**
- [ ] Implement onboard audio (always enabled)
- [ ] Implement Sonos discovery (cloud + SoCo fallback)
- [ ] Implement TOA system
- [ ] Create audio system priority logic
- [ ] Add audio system health checks

### **Phase 4: API & Frontend (Week 7-8)**
- [ ] Build FastAPI backend with all endpoints
- [ ] Implement WebSocket for real-time updates
- [ ] Create React/Vue frontend
- [ ] Add PIN protection for settings
- [ ] Implement polling and manual refresh

### **Phase 5: Monitoring & Testing (Week 9-10)**
- [ ] Setup logging (Loki/ELK)
- [ ] Configure Prometheus metrics
- [ ] Create Grafana dashboards
- [ ] Write comprehensive tests
- [ ] Setup CI/CD pipeline

### **Phase 6: Deployment & Hardening (Week 11-12)**
- [ ] Create systemd services
- [ ] Implement port conflict prevention
- [ ] Setup auto-restart mechanisms
- [ ] Configure alerting
- [ ] Load testing and optimization

---

## 14. **Key Success Criteria**

**Scheduler Reliability:**
- ✅ 99.99% on-time execution (within 5 seconds)
- ✅ Zero missed prayers
- ✅ Automatic recovery from failures

**Playback Guarantee:**
- ✅ Complete playback even with interruptions
- ✅ Watchdog detects and resolves issues
- ✅ Full audit trail in job_history

**System Stability:**
- ✅ Services auto-restart on failure
- ✅ No port conflicts
- ✅ Graceful shutdown/startup

**Monitoring:**
- ✅ Real-time visibility into all components
- ✅ Alerts on any anomaly
- ✅ Historical data for analysis

---