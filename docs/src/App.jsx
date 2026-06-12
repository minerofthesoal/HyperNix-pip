import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
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
  Sparkles
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

function App() {
  const [activeSection, setActiveSection] = useState('home')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [scrollY, setScrollY] = useState(0)

  useEffect(() => {
    const handleScroll = () => setScrollY(window.scrollY)
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const navItems = [
    { id: 'home', label: 'Home' },
    { id: 'features', label: 'Features' },
    { id: 'quickstart', label: 'Quickstart' },
    { id: 'models', label: 'Models' },
    { id: 'docs', label: 'Docs' }
  ]

  const scrollToSection = (id) => {
    const element = document.getElementById(id)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' })
      setActiveSection(id)
      setMobileMenuOpen(false)
    }
  }

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
              <span className="text-sm text-apple-text-secondary">v0.70.0 Now Available</span>
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
