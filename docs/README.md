# HyperNix Documentation Site

This directory contains the GitHub Pages documentation site for HyperNix.

## Features

- **Apple-inspired dark theme** with smooth animations
- **Responsive design** for all device sizes
- **Interactive sections**: Home, Features, Quickstart, Models, Docs
- **Framer Motion animations** for engaging user experience
- **Tailwind CSS** for rapid styling

## Sections

1. **Hero** - Introduction with animated terminal demo
2. **Features** - 8 core capabilities with icons and descriptions
3. **All Subsystems** - Complete list of hypernix modules
4. **Quickstart** - 4-step getting started guide
5. **Supported Models** - Model families grid
6. **Documentation** - Links to wiki deep-dives

## Development

```bash
# Install dependencies
npm install

# Run dev server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Deployment

The site is automatically deployed to GitHub Pages via the `.github/workflows/deploy-docs.yml` workflow when:
- Changes are pushed to `main` branch affecting `docs/`, `README.md`, or `wiki/`
- Manual trigger via GitHub Actions UI

## Tech Stack

- **React 18** - UI framework
- **Vite** - Build tool and dev server
- **Tailwind CSS** - Utility-first CSS
- **Framer Motion** - Animation library
- **Lucide React** - Icon library

## Customization

### Colors
Edit `tailwind.config.js` to customize the Apple-inspired color palette:
- `apple-black`: #000000
- `apple-dark`: #1a1a1a
- `apple-gray`: #2d2d2d
- `apple-accent`: #0071e3 (Apple blue)

### Animations
Custom keyframes and animation classes are defined in `tailwind.config.js`:
- `fade-in`, `slide-up`, `slide-down`, `scale-in`, `float`

### Content
Edit `src/App.jsx` to modify:
- Feature cards
- Quickstart steps
- Supported models
- Documentation links
