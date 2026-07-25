# Integrations with Tools

Besides using in the terminal and IDEs, Consilium CLI can also be integrated with other tools.

## Zsh plugin

[zsh-consilium](https://github.com/MoonshotAI/zsh-consilium) is a Zsh plugin that lets you quickly switch to Consilium CLI in Zsh.

**Installation**

If you use Oh My Zsh, you can install it like this:

```sh
git clone https://github.com/MoonshotAI/zsh-consilium.git \
  ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/consilium
```

Then add the plugin in `~/.zshrc`:

```sh
plugins=(... consilium)
```

Reload the Zsh configuration:

```sh
source ~/.zshrc
```

**Usage**

After installation, press `Ctrl-X` in Zsh to quickly switch to Consilium CLI without manually typing the `kimi` command.

::: tip
If you use other Zsh plugin managers (like zinit, zplug, etc.), please refer to the [zsh-consilium repository](https://github.com/MoonshotAI/zsh-consilium) README for installation instructions.
:::
