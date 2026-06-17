import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { marked } from 'marked'
import { 
  Terminal, 
  Cpu, 
  Download, 
  Zap, 
  BookOpen, 
  Code, 
  Layers, 
  ArrowRight,
  Github,
  ExternalLink,
  Menu,
  X,
  ChevronDown,
  CheckCircle,
  Play,
  Package,
  BarChart3,
  Brain,
  Sparkles,
  LineChart,
  Calendar,
  Clock,
  Heart,
  MessageCircle
} from 'lucide-react'

const features = [
  {
    icon: Download,
    title: 'Download',
    description: 'Pull snapshots from the Hub with short-name resolution, gated repos, and offline cache support.',
    color: '#0071e3'
  },
  {
    icon: Brain,
    title: 'Train',
    description: 'HyperNixConfig, HyperNixModel, init_from_scratch, expand_checkpoint, and full training loops.',
    color: '#bf5af2'
  },
  {
    icon: Code,
    title: 'Chat & Complete',
    description: 'CodeOven wrapper with .complete(), .chat(), .fill() methods. Chat templates for all major models.',
    color: '#ff9f0a'
  },
  {
    icon: Zap,
    title: 'Quantize',
    description: '30 quantization types from fp32/fp16 to IQ-quants. llama-quantize integration with automatic caching.',
    color: '#ffd60a'
  },
  {
    icon: Cpu,
    title: 'VRAM Management',
    description: 'OldFreezer (8-10GB), NewFreezer (11GB+), FlashFreezer (OOM-safe retry). 20 GPU presets included.',
    color: '#30d158'
  },
  {
    icon: BarChart3,
    title: 'Evaluate',
    description: '4-tier evaluation: Ristretto to Lungo. Run prompt batteries, score results, generate reports.',
    color: '#ff453a'
  },
  {
    icon: Layers,
    title: 'Preprocess',
    description: '5-tier data preprocessing pipeline: FryingPan → SaucePan → Skillet → GrillPan → Wok.',
    color: '#ac8dff'
  },
  {
    icon: Package,
    title: 'Ship',
    description: 'Push artifacts to HuggingFace Hub. GGUF conversion, upload utilities, and consistent dataset packaging.',
    color: '#00c7be'
  }
]

const subsystems = [
  { name: 'download', desc: 'Hub snapshot downloads' },
  { name: 'train', desc: 'Model training' },
  { name: 'old_oven / new_oven', desc: 'Inference wrappers' },
  { name: 'old_fridge / mediocre_fridge / new_fridge', desc: 'Memory & datasets' },
  { name: 'freezer', desc: 'VRAM management' },
  { name: 'smoke_alarm', desc: 'Training monitoring' },
  { name: 'pans / microwave', desc: 'Data & inference tiers' },
  { name: 'pressure_cooker', desc: 'AdamW optimizer' },
  { name: 'whisk', desc: 'Checkpoint averaging' },
  { name: 'cutting_board', desc: 'Train/val/test splits' },
  { name: 'countertop / bell / flour', desc: 'Chat session management' },
  { name: 'convert / quantize', desc: 'GGUF pipeline' },
  { name: 'upload', desc: 'Hub publishing' }
]

const quickstartSteps = [
  {
    step: '1',
    title: 'Install',
    code: 'pip install "hypernix[llama-cpp]"',
    description: 'Get started with core + llama-cpp-python bundled'
  },
  {
    step: '2',
    title: 'Chat',
    code: 'hypernix chat --repo-id nix2.5 --message "hello"',
    description: 'Chat with any supported model using short names'
  },
  {
    step: '3',
    title: 'Convert',
    code: 'hypernix --repo-id ray0rf1re/hyper-nix.1 --quants fp32 fp16 q4_k_m',
    description: 'Convert snapshots to GGUF with k-quants'
  },
  {
    step: '4',
    title: 'Train',
    code: 'python examples/train_hypernix_1_5_gtx1080.py',
    description: 'Train on consumer GPUs with automatic optimization'
  }
]

const supportedModels = [
  { family: 'HyperNix', models: ['hyper-nix.1', 'nix2.5', 'nix2.6', 'nix-2.7a'] },
  { family: 'Llama 3.x', models: ['llama-3.1-8b', 'llama-3.2-3b', 'llama-3.3-70b'] },
  { family: 'Qwen 2.5/3/3.5', models: ['qwen2.5-*', 'qwen3.5-4b', 'qwen3.5-35b'] },
  { family: 'Gemma 2/3/4', models: ['gemma-2-9b', 'gemma-3-4b', 'gemma-4-e4b'] },
  { family: 'Phi 3/4', models: ['phi-3-mini', 'phi-3.5-mini', 'phi-4'] },
  { family: 'DeepSeek', models: ['deepseek-r1-distill-llama-8b', 'deepseek-v3'] },
]

const wikiPages = [
  { name: 'Home', title: 'Home', desc: 'Wiki index and subsystem map' },
  { name: 'Ovens', title: 'Ovens', desc: 'Inference wrappers and chat templates' },
  { name: 'Fridges', title: 'Fridges', desc: 'Memory management and datasets' },
  { name: 'Freezer', title: 'Freezer', desc: 'VRAM optimization strategies' },
  { name: 'Alarms', title: 'Alarms', desc: 'Training monitoring and safety' },
  { name: 'Kitchen', title: 'Kitchen', desc: 'Pans, microwave, and pipelines' },
  { name: 'Training', title: 'Training', desc: 'Fine-tuning and expansion flows' },
  { name: 'Quantization', title: 'Quantization', desc: 'GGUF conversion guide' },
  { name: 'Pascal', title: 'Pascal GPUs', desc: 'GTX 1080 optimization playbook' },
  { name: 'CLI', title: 'CLI Reference', desc: 'Complete command cheat sheet' },
  { name: 'Architectures', title: 'Architectures', desc: 'Model architecture presets' },
  { name: 'Ranges', title: 'Ranges', desc: 'Labeling rubrics' },
  { name: 'Workshop', title: 'Workshop', desc: 'Model frameworks and TTS/ASR' },
  { name: 'Pressure-Cooker-V3', title: 'Pressure Cooker v3', desc: 'ZeRO-aware V3 optimizers and QAT' },
  { name: 'Abbicus', title: 'Abbicus', desc: 'Token regulation and curriculum' },
  { name: 'Frameworks', title: 'Frameworks', desc: 'ComputeFramework and workshop pipelines' },
  { name: 'Tupperware', title: 'Tupperware', desc: 'Dataset round splitting' },
  { name: 'Roadmap', title: 'Roadmap', desc: 'Planned releases' },
  { name: 'Changelog', title: 'Changelog', desc: 'Version history and release notes' },
  { name: 'macOS-legacy', title: 'macOS Legacy', desc: 'Running on old Intel Macs' },
  { name: 'Data-Pipeline', title: 'Data Pipeline', desc: '5-tier preprocessing from FryingPan to Wok' },
  { name: 'Evaluation', title: 'Evaluation', desc: '4-tier eval system: Ristretto to Lungo' },
  { name: 'Ship', title: 'Ship', desc: 'Push artifacts to HuggingFace Hub' },
  { name: 'VRAM-Profiles', title: 'VRAM Profiles', desc: '20 GPU presets for VRAM management' },
  { name: 'Chat-Templates', title: 'Chat Templates', desc: 'Templates for all major model families' },
  { name: 'Short-Names', title: 'Short Names', desc: 'Repository short-name resolution guide' },
  { name: 'Gated-Repos', title: 'Gated Repos', desc: 'Access gated models with HF tokens' },
  { name: 'Offline-Cache', title: 'Offline Cache', desc: 'Work offline with cached snapshots' },
  { name: 'Architecture-Presets', title: 'Architecture Presets', desc: 'Pre-configured model architectures' },
  { name: 'Optimizer-Config', title: 'Optimizer Config', desc: 'AdamW and ZeRO optimizer settings' },
]

function App() {
  const [activeSection, setActiveSection] = useState('home')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [scrollY, setScrollY] = useState(0)
  const [pypiVersion, setPypiVersion] = useState('0.70.3')
  const [wikiContent, setWikiContent] = useState({})
  const [activeWikiPage, setActiveWikiPage] = useState(null)
  const [stats, setStats] = useState({
    downloads: { last_day: 0, last_week: 0, last_month: 0 },
    github: { stars: 0, forks: 0, issues: 0 }
  })
  const [pypiInfo, setPypiInfo] = useState(null)
  const [pythonVersionStats, setPythonVersionStats] = useState([])
  const [systemStats, setSystemStats] = useState([])

  useEffect(() => {
    const handleScroll = () => setScrollY(window.scrollY)
    window.addEventListener('scroll', handleScroll)
    
    // Fetch from our local /v1/json endpoint first (fallback to PyPI API)
    fetch('./v1/json')
      .then(res => res.json())
      .then(data => {
        if (data.version) {
          setPypiVersion(data.version)
        }
        if (data.last_day !== undefined) {
          setStats(prev => ({
            ...prev,
            downloads: {
              last_day: data.last_day,
              last_week: data.last_week,
              last_month: data.last_month
            }
          }))
        }
      })
      .catch(err => {
        console.log('Failed to fetch local v1/json, using direct API fallback')
        // Fallback to direct PyPI API
        fetch('https://pypi.org/pypi/hypernix/json')
          .then(res => res.json())
          .then(pypiData => {
            if (pypiData.info) {
              setPypiVersion(pypiData.info.version)
            }
          })
          .catch(e => console.error('PyPI fallback failed:', e))
        
        // Fallback to pypistats
        fetch('https://pypistats.org/api/packages/hypernix/recent')
          .then(res => res.json())
          .then(pypiStatsData => {
            if (pypiStatsData.data) {
              setStats(prev => ({
                ...prev,
                downloads: pypiStatsData.data
              }))
            }
          })
          .catch(e => console.error('PyPIStats fallback failed:', e))
      })
    
    // Fetch Python version breakdown
    fetch('https://pypistats.org/api/packages/hypernix/python_minor')
      .then(res => res.json())
      .then(data => {
        if (data.data) {
          // Aggregate by version
          const versionMap = {}
          data.data.forEach(item => {
            if (item.category && item.category !== 'null') {
              versionMap[item.category] = (versionMap[item.category] || 0) + item.downloads
            }
          })
          const sorted = Object.entries(versionMap)
            .map(([version, downloads]) => ({ version, downloads }))
            .sort((a, b) => b.downloads - a.downloads)
          setPythonVersionStats(sorted)
        }
      })
      .catch(err => console.error('Failed to fetch Python version stats:', err))
    
    // Fetch OS breakdown
    fetch('https://pypistats.org/api/packages/hypernix/system')
      .then(res => res.json())
      .then(data => {
        if (data.data) {
          const osMap = {}
          data.data.forEach(item => {
            if (item.category && item.category !== 'null') {
              osMap[item.category] = (osMap[item.category] || 0) + item.downloads
            }
          })
          const sorted = Object.entries(osMap)
            .map(([os, downloads]) => ({ os, downloads }))
            .sort((a, b) => b.downloads - a.downloads)
          setSystemStats(sorted)
        }
      })
      .catch(err => console.error('Failed to fetch system stats:', err))
    
    // Fetch GitHub stats from GitHub API
    fetch('https://api.github.com/repos/minerofthesoal/hypernix-pip')
      .then(res => res.json())
      .then(data => {
        if (data.stargazers_count !== undefined) {
          setStats(prev => ({
            ...prev,
            github: {
              stars: data.stargazers_count,
              forks: data.forks_count,
              issues: data.open_issues_count
            }
          }))
        }
      })
      .catch(err => console.error('Failed to fetch GitHub stats:', err))
    
    // Fetch all wiki pages
    wikiPages.forEach(page => {
      fetch(`https://raw.githubusercontent.com/minerofthesoal/hypernix-pip/main/wiki/${page.name}.md`)
        .then(res => res.text())
        .then(markdown => {
          setWikiContent(prev => ({
            ...prev,
            [page.name]: marked.parse(markdown)
          }))
        })
        .catch(err => console.error(`Failed to fetch ${page.name}:`, err))
    })
    
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const navItems = [
    { id: 'home', label: 'Home' },
    { id: 'features', label: 'Features' },
    { id: 'quickstart', label: 'Quickstart' },
    { id: 'models', label: 'Models' },
    { id: 'docs', label: 'Docs' },
    { id: 'wiki', label: 'Wiki' },
    { id: 'stats', label: 'Stats' },
    { id: 'about', label: 'About' }
  ]

  const scrollToSection = (id) => {
    const element = document.getElementById(id)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' })
      setActiveSection(id)
      setMobileMenuOpen(false)
    }
  }

  const openWikiPage = (pageName) => {
    // Store current scroll position before opening
    const currentScroll = window.scrollY
    setActiveWikiPage(pageName)
    // Restore scroll position after state update
    setTimeout(() => {
      window.scrollTo(0, currentScroll)
    }, 0)
  }

  const closeWikiPage = () => {
    setActiveWikiPage(null)
  }

  // Download stats state
  const [downloadStats, setDownloadStats] = useState([])
  const [totalDownloads, setTotalDownloads] = useState(0)
  const [releaseTimeline, setReleaseTimeline] = useState([])
  const [pypiTotalDownloads, setPypiTotalDownloads] = useState(0)

  useEffect(() => {
    // Fetch PyPI download stats
    fetch('https://pypistats.org/api/packages/hypernix/recent')
      .then(res => res.json())
      .then(data => {
        if (data.data) {
          const recent = data.data
          const downloads = [
            { period: 'Last day', count: recent.last_day || 0 },
            { period: 'Last week', count: recent.last_week || 0 },
            { period: 'Last month', count: recent.last_month || 0 }
          ]
          setDownloadStats(downloads)
          setTotalDownloads(recent.last_month || 0)
        }
      })
      .catch(err => console.error('Failed to fetch download stats:', err))

    // Fetch total downloads from PyPI
    fetch('https://pypistats.org/api/packages/hypernix/overall')
      .then(res => res.json())
      .then(data => {
        if (data.data && data.data.total_downloads) {
          setPypiTotalDownloads(data.data.total_downloads)
        }
      })
      .catch(err => console.error('Failed to fetch total downloads:', err))

    // Fetch GitHub releases for timeline
    fetch('https://api.github.com/repos/minerofthesoal/hypernix-pip/releases')
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          const timeline = data.slice(0, 15).map(release => ({
            version: release.tag_name,
            date: new Date(release.published_at).toLocaleDateString(),
            description: release.body?.split('\n')[0] || 'Release',
            isPreRelease: release.prerelease,
            url: release.html_url
          }))
          setReleaseTimeline(timeline)
        }
      })
      .catch(err => console.error('Failed to fetch releases:', err))
  }, [])

  return (
    <div className="min-h-screen bg-apple-black text-apple-text">
      {/* Navigation */}
      <motion.nav 
        initial={{ y: -100 }}
        animate={{ y: 0 }}
        className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
          scrollY > 50 ? 'glass-strong border-b border-apple-gray' : 'bg-transparent'
        }`}
      >
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <motion.div 
              className="flex items-center space-x-3 cursor-pointer"
              whileHover={{ scale: 1.05 }}
              onClick={() => scrollToSection('home')}
            >
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-apple-accent to-purple-600 flex items-center justify-center glow-accent">
                <Sparkles className="w-6 h-6 text-white" />
              </div>
              <span className="text-xl font-semibold gradient-text">hypernix</span>
            </motion.div>

            {/* Desktop Nav */}
            <div className="hidden md:flex items-center space-x-8">
              {navItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => scrollToSection(item.id)}
                  className={`text-sm transition-all duration-300 relative group ${
                    activeSection === item.id 
                      ? 'text-apple-accent' 
                      : 'text-apple-text-secondary hover:text-apple-text'
                  }`}
                >
                  {item.label}
                  <span className={`absolute -bottom-1 left-0 h-0.5 bg-apple-accent transition-all duration-300 ${
                    activeSection === item.id ? 'w-full' : 'w-0 group-hover:w-full'
                  }`} />
                </button>
              ))}
              <a
                href="https://github.com/minerofthesoal/hypernix-pip"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center space-x-2 text-apple-text-secondary hover:text-apple-text transition-all duration-300 group"
              >
                <Github className="w-5 h-5 group-hover:scale-110 transition-transform" />
                <span className="text-sm">GitHub</span>
              </a>
            </div>

            {/* Mobile menu button */}
            <button
              className="md:hidden text-apple-text"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            >
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="md:hidden bg-apple-dark border-b border-apple-gray"
            >
              <div className="px-6 py-4 space-y-4">
                {navItems.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => scrollToSection(item.id)}
                    className="block w-full text-left text-apple-text-secondary hover:text-apple-text py-2"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.nav>

      {/* Hero Section */}
      <section id="home" className="pt-32 pb-20 px-6">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
            className="text-center"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.6, delay: 0.2 }}
              className="inline-flex items-center space-x-2 px-4 py-2 rounded-full bg-apple-gray/50 border border-apple-light-gray mb-8"
            >
              <Sparkles className="w-4 h-4 text-apple-accent" />
              <span className="text-sm text-apple-text-secondary">v{pypiVersion} Now Available</span>
            </motion.div>

            <h1 className="text-5xl md:text-7xl font-bold mb-6 gradient-text">
              End-to-end toolkit for<br />
              <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent glow-accent-hover inline-block">
                PyTorch language models
              </span>
            </h1>

            <p className="text-xl text-apple-text-secondary max-w-3xl mx-auto mb-12">
              The complete kitchen for the HyperNix family — download, chat, fine-tune, 
              evaluate, quantize, and ship. Chat-tuned ray0rf1re/hyper-Nix.2 and original 
              hyper-nix.1 fully supported.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => scrollToSection('quickstart')}
                className="px-8 py-4 bg-apple-accent hover:bg-apple-accent-hover text-white rounded-full font-medium flex items-center space-x-2 transition-all duration-300 glow-accent hover:glow-accent-hover"
              >
                <Play className="w-5 h-5" />
                <span>Get Started</span>
              </motion.button>
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => scrollToSection('docs')}
                className="px-8 py-4 glass-light hover:bg-apple-light-gray text-apple-text rounded-full font-medium flex items-center space-x-2 transition-all duration-300 border border-apple-gray hover:border-apple-accent/50"
              >
                <BookOpen className="w-5 h-5" />
                <span>View Docs</span>
              </motion.button>
            </div>

            {/* Stats Section */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.4 }}
              className="mt-16 grid grid-cols-2 md:grid-cols-4 gap-4 max-w-3xl mx-auto"
            >
              <div className="glass rounded-xl p-4 border border-apple-gray text-center">
                <div className="text-3xl font-bold text-apple-accent">
                  {stats.downloads.last_day.toLocaleString()}
                </div>
                <div className="text-xs text-apple-text-secondary mt-1">Downloads (24h)</div>
              </div>
              <div className="glass rounded-xl p-4 border border-apple-gray text-center">
                <div className="text-3xl font-bold text-apple-accent">
                  {stats.downloads.last_week.toLocaleString()}
                </div>
                <div className="text-xs text-apple-text-secondary mt-1">Downloads (7d)</div>
              </div>
              <div className="glass rounded-xl p-4 border border-apple-gray text-center">
                <div className="text-3xl font-bold text-apple-accent">
                  {stats.github.stars.toLocaleString()}
                </div>
                <div className="text-xs text-apple-text-secondary mt-1">GitHub Stars</div>
              </div>
              <div className="glass rounded-xl p-4 border border-apple-gray text-center">
                <div className="text-3xl font-bold text-apple-accent">
                  {stats.github.forks.toLocaleString()}
                </div>
                <div className="text-xs text-apple-text-secondary mt-1">GitHub Forks</div>
              </div>
            </motion.div>
          </motion.div>

          {/* Hero animation */}
          <motion.div
            initial={{ opacity: 0, y: 50 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="mt-20 relative"
          >
            <div className="absolute inset-0 bg-gradient-to-t from-apple-black via-transparent to-transparent z-10" />
            <motion.div
              animate={{ y: [-10, 10, -10] }}
              transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
              className="glass rounded-2xl border border-apple-gray p-6 overflow-hidden border-glow"
            >
              <div className="flex items-center space-x-2 mb-4">
                <div className="w-3 h-3 rounded-full bg-red-500" />
                <div className="w-3 h-3 rounded-full bg-yellow-500" />
                <div className="w-3 h-3 rounded-full bg-green-500" />
                <Terminal className="w-4 h-4 text-apple-text-secondary ml-4" />
              </div>
              <code className="text-sm text-apple-text-secondary font-mono">
                <span className="text-apple-accent">$</span> pip install hypernix<br />
                <span className="text-apple-accent">$</span> hypernix chat --repo-id nix2.5 --message "hello"<br />
                <span className="text-apple-text">╭─ system</span><br />
                <span className="text-apple-text-secondary">│ You are a helpful assistant.</span><br />
                <span className="text-apple-accent">╰─ user</span><br />
                <span className="text-apple-text">Hello! How can I help you today?</span>
              </code>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-20 px-6 bg-apple-dark">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="text-center mb-16"
          >
            <h2 className="text-4xl md:text-5xl font-bold mb-4">
              Everything in your<br />
              <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent">
                ML kitchen
              </span>
            </h2>
            <p className="text-apple-text-secondary text-lg max-w-2xl mx-auto">
              A complete toolkit covering every stage of your language model workflow
            </p>
          </motion.div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            {features.map((feature, index) => (
              <motion.div
                key={feature.title}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: index * 0.1 }}
                whileHover={{ y: -5, scale: 1.02 }}
                className="glass rounded-2xl p-6 border border-apple-gray hover:border-apple-accent/50 transition-all duration-300 border-glow"
              >
                <div 
                  className="w-12 h-12 rounded-xl flex items-center justify-center mb-4 glow-accent"
                  style={{ backgroundColor: `${feature.color}20` }}
                >
                  <feature.icon className="w-6 h-6" style={{ color: feature.color }} />
                </div>
                <h3 className="text-xl font-semibold mb-2">{feature.title}</h3>
                <p className="text-apple-text-secondary text-sm leading-relaxed">
                  {feature.description}
                </p>
              </motion.div>
            ))}
          </div>

          {/* Subsystems list */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="mt-16 glass rounded-2xl p-8 border border-apple-gray border-glow"
          >
            <h3 className="text-2xl font-semibold mb-6 text-center">All Subsystems</h3>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
              {subsystems.map((sub) => (
                <div key={sub.name} className="flex items-start space-x-3">
                  <CheckCircle className="w-5 h-5 text-apple-accent flex-shrink-0 mt-0.5" />
                  <div>
                    <code className="text-apple-accent text-sm">{sub.name}</code>
                    <p className="text-apple-text-secondary text-sm">{sub.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      {/* Quickstart Section */}
      <section id="quickstart" className="py-20 px-6">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="text-center mb-16"
          >
            <h2 className="text-4xl md:text-5xl font-bold mb-4">
              Get started in<br />
              <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent">
                minutes
              </span>
            </h2>
            <p className="text-apple-text-secondary text-lg max-w-2xl mx-auto">
              From installation to your first model interaction
            </p>
          </motion.div>

          <div className="grid md:grid-cols-2 gap-6">
            {quickstartSteps.map((item, index) => (
              <motion.div
                key={item.step}
                initial={{ opacity: 0, x: index % 2 === 0 ? -30 : 30 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: index * 0.1 }}
                className="glass rounded-2xl p-6 border border-apple-gray border-glow"
              >
                <div className="flex items-start space-x-4">
                  <div className="w-10 h-10 rounded-full bg-apple-accent flex items-center justify-center flex-shrink-0">
                    <span className="text-white font-bold">{item.step}</span>
                  </div>
                  <div className="flex-1">
                    <h3 className="text-xl font-semibold mb-2">{item.title}</h3>
                    <p className="text-apple-text-secondary text-sm mb-4">{item.description}</p>
                    <div className="bg-apple-black rounded-lg p-4 border border-apple-gray">
                      <code className="text-sm text-apple-accent font-mono">{item.code}</code>
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Supported Models Section */}
      <section id="models" className="py-20 px-6 bg-apple-dark">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="text-center mb-16"
          >
            <h2 className="text-4xl md:text-5xl font-bold mb-4">
              Supported<br />
              <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent">
                model families
              </span>
            </h2>
            <p className="text-apple-text-secondary text-lg max-w-2xl mx-auto">
              Short names resolve automatically. Use them in CLI and Python APIs.
            </p>
          </motion.div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {supportedModels.map((group, index) => (
              <motion.div
                key={group.family}
                initial={{ opacity: 0, scale: 0.95 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: index * 0.1 }}
                whileHover={{ y: -5, scale: 1.02 }}
                className="glass rounded-2xl p-6 border border-apple-gray border-glow transition-all duration-300"
              >
                <h3 className="text-lg font-semibold mb-4 text-apple-accent">{group.family}</h3>
                <div className="space-y-2">
                  {group.models.map((model) => (
                    <div key={model} className="flex items-center space-x-2">
                      <div className="w-1.5 h-1.5 rounded-full bg-apple-accent" />
                      <code className="text-sm text-apple-text-secondary">{model}</code>
                    </div>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="mt-8 text-center"
          >
            <p className="text-apple-text-secondary text-sm mb-4">
              And many more: GLM, Mistral, Mixtral, NVIDIA Nemotron, OpenAI gpt-oss...
            </p>
            <a
              href="https://github.com/minerofthesoal/hypernix-pip#supported-model-families"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center space-x-2 text-apple-accent hover:text-apple-accent-hover transition-all duration-300 group"
            >
              <span>View full registry</span>
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </a>
          </motion.div>
        </div>
      </section>

      {/* Documentation Section */}
      <section id="docs" className="py-20 px-6">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="text-center mb-16"
          >
            <h2 className="text-4xl md:text-5xl font-bold mb-4">
              Deep dive<br />
              <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent">
                documentation
              </span>
            </h2>
            <p className="text-apple-text-secondary text-lg max-w-2xl mx-auto">
              Comprehensive guides for every subsystem
            </p>
          </motion.div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[
              { title: 'Ovens', desc: 'Inference wrappers and chat templates', icon: Code },
              { title: 'Fridges', desc: 'Memory management and datasets', icon: Layers },
              { title: 'Freezer', desc: 'VRAM optimization strategies', icon: Cpu },
              { title: 'Alarms', desc: 'Training monitoring and safety', icon: Zap },
              { title: 'Kitchen', desc: 'Pans, microwave, and pipelines', icon: Package },
              { title: 'Training', desc: 'Fine-tuning and expansion flows', icon: Brain },
              { title: 'Quantization', desc: 'GGUF conversion guide', icon: Download },
              { title: 'Pascal GPUs', desc: 'GTX 1080 optimization playbook', icon: Terminal },
              { title: 'CLI Reference', desc: 'Complete command cheat sheet', icon: BookOpen },
              { title: 'Data Pipeline', desc: '5-tier preprocessing system', icon: BarChart3 },
              { title: 'Evaluation', desc: '4-tier evaluation framework', icon: LineChart },
              { title: 'Ship', desc: 'Publish to HuggingFace Hub', icon: ExternalLink },
              { title: 'VRAM Profiles', desc: '20 GPU preset configurations', icon: Cpu },
              { title: 'Chat Templates', desc: 'Templates for major models', icon: MessageCircle },
              { title: 'Short Names', desc: 'Repository short-name guide', icon: BookOpen },
            ].map((doc, index) => (
              <motion.a
                key={doc.title}
                href={`https://github.com/minerofthesoal/hypernix-pip/blob/main/wiki/${doc.title.replace(' ', '-')}.md`}
                target="_blank"
                rel="noopener noreferrer"
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: index * 0.08 }}
                whileHover={{ y: -5, scale: 1.02 }}
                className="glass rounded-2xl p-6 border border-apple-gray hover:border-apple-accent/50 transition-all duration-300 group border-glow"
              >
                <doc.icon className="w-8 h-8 text-apple-accent mb-4 group-hover:scale-110 transition-transform glow-accent" />
                <h3 className="text-xl font-semibold mb-2">{doc.title}</h3>
                <p className="text-apple-text-secondary text-sm">{doc.desc}</p>
                <div className="mt-4 flex items-center space-x-2 text-apple-accent text-sm">
                  <span>Read more</span>
                  <ExternalLink className="w-4 h-4" />
                </div>
              </motion.a>
            ))}
          </div>
        </div>
      </section>

      {/* Wiki Section */}
      <section id="wiki" className="py-20 px-6 bg-apple-dark">
        <div className="max-w-7xl mx-auto">
          {activeWikiPage ? (
            /* Wiki Page View */
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
            >
              <button
                onClick={closeWikiPage}
                className="mb-6 flex items-center space-x-2 text-apple-accent hover:text-apple-accent-hover transition-all duration-300 group"
              >
                <ArrowRight className="w-4 h-4 rotate-180 group-hover:-translate-x-1 transition-transform" />
                <span>Back to Wiki Index</span>
              </button>
              
              <div className="glass rounded-2xl p-8 border border-apple-gray border-glow">
                <div 
                  className="prose prose-invert max-w-none"
                  dangerouslySetInnerHTML={{ __html: wikiContent[activeWikiPage] || '<p>Loading...</p>' }}
                />
              </div>
            </motion.div>
          ) : (
            /* Wiki Index */
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6 }}
              className="text-center mb-16"
            >
              <h2 className="text-4xl md:text-5xl font-bold mb-4">
                Wiki<br />
                <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent">
                  Documentation
                </span>
              </h2>
              <p className="text-apple-text-secondary text-lg max-w-2xl mx-auto mb-12">
                Deep-dive reference guides for every subsystem — auto-updated from the repository
              </p>

              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                {wikiPages.map((page, index) => (
                  <motion.button
                    key={page.name}
                    onClick={() => openWikiPage(page.name)}
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.5, delay: index * 0.05 }}
                    whileHover={{ y: -5, scale: 1.02 }}
                    className="glass rounded-2xl p-6 border border-apple-gray hover:border-apple-accent/50 transition-all duration-300 group border-glow text-left w-full"
                  >
                    <BookOpen className="w-8 h-8 text-apple-accent mb-4 group-hover:scale-110 transition-transform glow-accent" />
                    <h3 className="text-xl font-semibold mb-2">{page.title}</h3>
                    <p className="text-apple-text-secondary text-sm">{page.desc}</p>
                    <div className="mt-4 flex items-center space-x-2 text-apple-accent text-sm">
                      <span>Read more</span>
                      <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                    </div>
                  </motion.button>
                ))}
              </div>
            </motion.div>
          )}
        </div>
      </section>

      {/* Stats Section */}
      <section id="stats" className="py-20 px-6 bg-apple-dark">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="text-center mb-16"
          >
            <h2 className="text-4xl md:text-5xl font-bold mb-4">
              Download<br />
              <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent">
                Statistics
              </span>
            </h2>
            <p className="text-apple-text-secondary text-lg max-w-2xl mx-auto mb-8">
              Real-time download data from PyPI
            </p>
          </motion.div>

          {/* Download Counter Cards */}
          <div className="grid md:grid-cols-4 gap-6 mb-12">
            {/* Total Downloads Card */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: 0 }}
              className="glass rounded-2xl p-8 border border-apple-gray border-glow text-center"
            >
              <Download className="w-10 h-10 text-apple-accent mx-auto mb-4 glow-accent" />
              <h3 className="text-3xl font-bold text-apple-accent mb-2">
                {pypiTotalDownloads.toLocaleString()}
              </h3>
              <p className="text-apple-text-secondary">Total Downloads</p>
            </motion.div>
            {downloadStats.map((stat, index) => (
              <motion.div
                key={stat.period}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: (index + 1) * 0.1 }}
                className="glass rounded-2xl p-8 border border-apple-gray border-glow text-center"
              >
                <Download className="w-10 h-10 text-apple-accent mx-auto mb-4 glow-accent" />
                <h3 className="text-3xl font-bold text-apple-accent mb-2">
                  {stat.count.toLocaleString()}
                </h3>
                <p className="text-apple-text-secondary">{stat.period}</p>
              </motion.div>
            ))}
          </div>

          {/* Download Graph Visualization */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="glass rounded-2xl p-8 border border-apple-gray border-glow mb-12"
          >
            <h3 className="text-2xl font-semibold mb-6 flex items-center space-x-3">
              <LineChart className="w-6 h-6 text-apple-accent" />
              <span>Download Trend</span>
            </h3>
            <div className="h-48 flex items-end justify-around space-x-2">
              {downloadStats.map((stat, index) => {
                const maxCount = Math.max(...downloadStats.map(s => s.count), 1)
                const heightPercent = (stat.count / maxCount) * 100
                return (
                  <div key={stat.period} className="flex-1 flex flex-col items-center">
                    <motion.div
                      initial={{ height: 0 }}
                      whileInView={{ height: `${heightPercent}%` }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.8, delay: index * 0.2 }}
                      className="w-full bg-gradient-to-t from-apple-accent to-purple-600 rounded-t-lg glow-accent"
                      style={{ minHeight: '4px' }}
                    />
                    <span className="text-xs text-apple-text-secondary mt-2 text-center">{stat.period.split(' ')[1]}</span>
                  </div>
                )
              })}
            </div>
          </motion.div>

          {/* Release Timeline */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="glass rounded-2xl p-8 border border-apple-gray border-glow"
          >
            <h3 className="text-2xl font-semibold mb-6 flex items-center space-x-3">
              <Calendar className="w-6 h-6 text-apple-accent" />
              <span>Release Timeline</span>
            </h3>
            <div className="space-y-4">
              {releaseTimeline.length > 0 ? (
                releaseTimeline.map((release, index) => (
                  <motion.div
                    key={release.version}
                    initial={{ opacity: 0, x: -20 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.5, delay: index * 0.1 }}
                    className="flex items-start space-x-4 p-4 rounded-lg hover:bg-apple-black/50 transition-all duration-300"
                  >
                    <div className={`w-3 h-3 rounded-full mt-1.5 ${release.isPreRelease ? 'bg-yellow-500' : 'bg-green-500'} glow-accent`} />
                    <div className="flex-1">
                      <div className="flex items-center space-x-3">
                        <a 
                          href={release.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-apple-accent hover:text-apple-accent-hover font-medium transition-colors"
                        >
                          {release.version}
                        </a>
                        {release.isPreRelease && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-500/20 text-yellow-500">
                            Pre-release
                          </span>
                        )}
                        <span className="text-xs text-apple-text-secondary flex items-center space-x-1">
                          <Clock className="w-3 h-3" />
                          <span>{release.date}</span>
                        </span>
                      </div>
                      <p className="text-apple-text-secondary text-sm mt-1">{release.description}</p>
                    </div>
                  </motion.div>
                ))
              ) : (
                <p className="text-apple-text-secondary text-center py-8">Loading releases...</p>
              )}
            </div>
          </motion.div>

          {/* GitHub Stats */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="glass rounded-2xl p-8 border border-apple-gray border-glow mt-8"
          >
            <h3 className="text-2xl font-semibold mb-6 flex items-center space-x-3">
              <Github className="w-6 h-6 text-apple-accent" />
              <span>GitHub Repository Stats</span>
            </h3>
            <div className="grid md:grid-cols-3 gap-6">
              <div className="text-center">
                <div className="text-3xl font-bold text-apple-accent mb-2">{stats.github.stars.toLocaleString()}</div>
                <div className="text-apple-text-secondary">Stars</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-apple-accent mb-2">{stats.github.forks.toLocaleString()}</div>
                <div className="text-apple-text-secondary">Forks</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-apple-accent mb-2">{stats.github.issues.toLocaleString()}</div>
                <div className="text-apple-text-secondary">Open Issues</div>
              </div>
            </div>
          </motion.div>

          {/* Python Version Stats */}
          {pythonVersionStats.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: 0.5 }}
              className="glass rounded-2xl p-8 border border-apple-gray border-glow mt-8"
            >
              <h3 className="text-2xl font-semibold mb-6 flex items-center space-x-3">
                <Code className="w-6 h-6 text-apple-accent" />
                <span>Downloads by Python Version</span>
              </h3>
              <div className="space-y-3">
                {pythonVersionStats.slice(0, 10).map((item, index) => {
                  const maxDownloads = pythonVersionStats[0].downloads
                  const percent = (item.downloads / maxDownloads) * 100
                  return (
                    <div key={item.version} className="flex items-center space-x-4">
                      <div className="w-20 text-sm text-apple-text-secondary font-mono">{item.version}</div>
                      <div className="flex-1 h-6 bg-apple-black/50 rounded-full overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          whileInView={{ width: `${percent}%` }}
                          viewport={{ once: true }}
                          transition={{ duration: 0.8, delay: index * 0.1 }}
                          className="h-full bg-gradient-to-r from-apple-accent to-purple-600 glow-accent"
                        />
                      </div>
                      <div className="w-24 text-right text-sm text-apple-text">{item.downloads.toLocaleString()}</div>
                    </div>
                  )
                })}
              </div>
            </motion.div>
          )}

          {/* System/OS Stats */}
          {systemStats.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: 0.6 }}
              className="glass rounded-2xl p-8 border border-apple-gray border-glow mt-8"
            >
              <h3 className="text-2xl font-semibold mb-6 flex items-center space-x-3">
                <Cpu className="w-6 h-6 text-apple-accent" />
                <span>Downloads by Operating System</span>
              </h3>
              <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
                {systemStats.map((item, index) => (
                  <motion.div
                    key={item.os}
                    initial={{ opacity: 0, scale: 0.9 }}
                    whileInView={{ opacity: 1, scale: 1 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.5, delay: index * 0.1 }}
                    className="glass rounded-xl p-6 border border-apple-gray border-glow text-center"
                  >
                    <div className="text-2xl font-bold text-apple-accent mb-2">{item.downloads.toLocaleString()}</div>
                    <div className="text-apple-text-secondary capitalize">{item.os}</div>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          )}

          {/* PyPI Package Info */}
          {pypiInfo && (
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: 0.7 }}
              className="glass rounded-2xl p-8 border border-apple-gray border-glow mt-8"
            >
              <h3 className="text-2xl font-semibold mb-6 flex items-center space-x-3">
                <Package className="w-6 h-6 text-apple-accent" />
                <span>Package Information</span>
              </h3>
              <div className="grid md:grid-cols-2 gap-6">
                <div>
                  <div className="text-sm text-apple-text-secondary mb-1">Latest Version</div>
                  <div className="text-xl font-semibold text-apple-accent">{pypiInfo.version}</div>
                </div>
                <div>
                  <div className="text-sm text-apple-text-secondary mb-1">License</div>
                  <div className="text-xl font-semibold text-apple-text">{pypiInfo.license || 'N/A'}</div>
                </div>
                <div>
                  <div className="text-sm text-apple-text-secondary mb-1">Author</div>
                  <div className="text-xl font-semibold text-apple-text">{pypiInfo.author || 'N/A'}</div>
                </div>
                <div>
                  <div className="text-sm text-apple-text-secondary mb-1">Home Page</div>
                  <a href={pypiInfo.home_page} target="_blank" rel="noopener noreferrer" className="text-xl font-semibold text-apple-accent hover:text-apple-accent-hover transition-colors flex items-center space-x-2">
                    <span>{pypiInfo.home_page}</span>
                    <ExternalLink className="w-4 h-4" />
                  </a>
                </div>
              </div>
              <div className="mt-6">
                <div className="text-sm text-apple-text-secondary mb-2">Summary</div>
                <p className="text-apple-text">{pypiInfo.summary}</p>
              </div>
            </motion.div>
          )}
        </div>
      </section>

      {/* About Section */}
      <section id="about" className="py-20 px-6">
        <div className="max-w-4xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="text-center mb-12"
          >
            <h2 className="text-4xl md:text-5xl font-bold mb-4">
              About<br />
              <span className="bg-gradient-to-r from-apple-accent to-purple-600 bg-clip-text text-transparent">
                Hypernix
              </span>
            </h2>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="glass rounded-2xl p-8 border border-apple-gray border-glow"
          >
            <div className="prose prose-invert max-w-none">
              <p className="text-apple-text-secondary leading-relaxed mb-6">
                I made this project for fun after getting a new PC (even though my GPU is now 10 years old). 
                I wanted to train LLMs on it within a reasonable time, but it turns out that takes a while — 
                and not having any tensor cores doesn't help. Not long after, I got access to Claude Code with 
                Opus version 4.6 and later v4.7, and built this to help accomplish my task better.
              </p>
              <p className="text-apple-text-secondary leading-relaxed mb-6">
                Someday I'll build a new PC and rewrite this without any AI assistance, but first I need to 
                learn more Python. Once I do, I really hope many people use the package and find it very useful. 
                In version 2.00.X, I plan to do a full 100% rewrite of the package — no AI slop, written by me 
                and possibly a few friends.
              </p>
              <p className="text-apple-text leading-relaxed mb-8">
                Anyway, thanks for using Hypernix.
              </p>
            </div>

            {/* Connect Section */}
            <div className="mt-12 pt-8 border-t border-apple-gray">
              <h3 className="text-2xl font-semibold mb-6 text-center flex items-center justify-center space-x-3">
                <MessageCircle className="w-6 h-6 text-apple-accent" />
                <span>Connect With Me</span>
              </h3>
              <div className="flex flex-wrap justify-center gap-6">
                <motion.a
                  href="https://github.com/minerofthesoal"
                  target="_blank"
                  rel="noopener noreferrer"
                  whileHover={{ scale: 1.05, y: -3 }}
                  className="flex items-center space-x-3 px-6 py-4 glass rounded-xl border border-apple-gray hover:border-apple-accent/50 transition-all duration-300 group"
                >
                  <Github className="w-6 h-6 text-apple-accent group-hover:scale-110 transition-transform" />
                  <span className="text-apple-text group-hover:text-apple-accent transition-colors">GitHub</span>
                </motion.a>
                <motion.a
                  href="https://huggingface.co/ray0rf1re"
                  target="_blank"
                  rel="noopener noreferrer"
                  whileHover={{ scale: 1.05, y: -3 }}
                  className="flex items-center space-x-3 px-6 py-4 glass rounded-xl border border-apple-gray hover:border-apple-accent/50 transition-all duration-300 group"
                >
                  <Heart className="w-6 h-6 text-apple-accent group-hover:scale-110 transition-transform" />
                  <span className="text-apple-text group-hover:text-apple-accent transition-colors">Hugging Face</span>
                </motion.a>
                <motion.a
                  href="https://steamcommunity.com/id/transgenderfireball/"
                  target="_blank"
                  rel="noopener noreferrer"
                  whileHover={{ scale: 1.05, y: -3 }}
                  className="flex items-center space-x-3 px-6 py-4 glass rounded-xl border border-apple-gray hover:border-apple-accent/50 transition-all duration-300 group"
                >
                  <svg className="w-6 h-6 text-apple-accent group-hover:scale-110 transition-transform" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.065 1.8 2.805 1.29 3.495.975.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-6.27 0-1.38.45-2.535 1.185-3.435-.24-.36-.51-1.095.12-2.28 0 0 2.16-.675 7.05 2.64 2.085-.585 4.335-.87 6.585-.87 2.25 0 4.5.285 6.585.87 4.89-3.33 7.05-2.64 7.05-2.64.63 1.185.36 1.92.12 2.28.75.9 1.185 2.04 1.185 3.435 0 4.95-2.805 5.97-5.475 6.27.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
                  </svg>
                  <span className="text-apple-text group-hover:text-apple-accent transition-colors">Steam</span>
                </motion.a>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-6 border-t border-apple-gray glass">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center space-x-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-apple-accent to-purple-600 flex items-center justify-center glow-accent">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <span className="text-lg font-semibold gradient-text">hypernix</span>
            </div>

            <div className="flex items-center space-x-6 text-sm text-apple-text-secondary">
              <a href="https://pypi.org/project/hypernix/" target="_blank" rel="noopener noreferrer" className="hover:text-apple-text transition-all duration-300 group">
                PyPI
              </a>
              <a href="https://github.com/minerofthesoal/hypernix-pip" target="_blank" rel="noopener noreferrer" className="hover:text-apple-text transition-all duration-300 group">
                GitHub
              </a>
              <a href="https://huggingface.co/ray0rf1re" target="_blank" rel="noopener noreferrer" className="hover:text-apple-text transition-all duration-300 group">
                Hugging Face
              </a>
            </div>

            <p className="text-sm text-apple-text-secondary">
              Apache-2.0 License
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
