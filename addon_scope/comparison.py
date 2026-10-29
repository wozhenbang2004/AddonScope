"""Relate package candidates to observations without guessing the winning version."""

from dataclasses import asdict


def package_comparison(result, finding):
    groups = []
    for name in finding.packages:
        providers = [dist for dist in result.distributions if dist.name == name]
        modules = {module for dist in providers for module in dist.modules}
        loaded = {module: path for module, path in sorted(result.loaded.items())
                  if module.split(".", 1)[0] in modules}
        groups.append({"package": name, "providers": [asdict(dist) for dist in providers],
                       "loaded": loaded})
    return groups
