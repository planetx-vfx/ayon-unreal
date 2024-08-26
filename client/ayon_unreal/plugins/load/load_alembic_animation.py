# -*- coding: utf-8 -*-
"""Load Alembic Animation."""
import os

from ayon_core.lib import EnumDef
from ayon_core.pipeline import (
    get_representation_path,
    AYON_CONTAINER_ID
)
from ayon_unreal.api import plugin
from ayon_unreal.api import pipeline as unreal_pipeline
import unreal  # noqa


class AnimationAlembicLoader(plugin.Loader):
    """Load Unreal SkeletalMesh from Alembic"""

    product_types = {"animation"}
    label = "Import Alembic Animation"
    representations = {"abc"}
    icon = "cube"
    color = "orange"
    abc_conversion_preset = "maya"
    show_dialog = False

    @classmethod
    def apply_settings(cls, project_settings):
        super(AnimationAlembicLoader, cls).apply_settings(project_settings)
        # Apply import settings
        unreal_settings = project_settings.get("unreal", {})
        if unreal_settings.get("abc_conversion_preset", cls.abc_conversion_preset):
            cls.abc_conversion_preset = unreal_settings.get(
                "abc_conversion_preset", cls.abc_conversion_preset)
        if unreal_settings.get("show_dialog", cls.show_dialog):
            cls.show_dialog = unreal_settings.get(
                "show_dialog", cls.show_dialog)

    @classmethod
    def get_options(cls, contexts):
        return [
            EnumDef(
                "abc_conversion_preset",
                label="Alembic Conversion Preset",
                items={
                    "custom": "custom",
                    "maya": "maya"
                },
                default=cls.abc_conversion_preset
            )
        ]

    def get_task(self, filename, asset_dir, asset_name, replace, loaded_options=None):
        task = unreal.AssetImportTask()
        options = unreal.AbcImportSettings()
        sm_settings = unreal.AbcStaticMeshSettings()
        conversion_settings = unreal.AbcConversionSettings()
        abc_conversion_preset = loaded_options.get("abc_conversion_preset")
        if abc_conversion_preset == "maya":
            conversion_settings = unreal.AbcConversionSettings(
                preset= unreal.AbcConversionPreset.MAYA)
        else:
            conversion_settings = unreal.AbcConversionSettings(
                preset=unreal.AbcConversionPreset.CUSTOM,
                flip_u=False, flip_v=False,
                rotation=[0.0, 0.0, 0.0],
                scale=[1.0, 1.0, 1.0])

        options.sampling_settings.frame_start = loaded_options.get("frameStart")
        options.sampling_settings.frame_end = loaded_options.get("frameEnd")
        task.set_editor_property('filename', filename)
        task.set_editor_property('destination_path', asset_dir)
        task.set_editor_property('destination_name', asset_name)
        task.set_editor_property('replace_existing', replace)
        task.set_editor_property('automated', not self.show_dialog)
        task.set_editor_property('save', True)

        options.set_editor_property(
            'import_type', unreal.AlembicImportType.SKELETAL)

        options.static_mesh_settings = sm_settings
        options.conversion_settings = conversion_settings
        task.options = options

        return task

    def load(self, context, name, namespace, options):
        """Load and containerise representation into Content Browser.

        This is two-step process. First, import FBX to temporary path and
        then call `containerise()` on it - this moves all content to new
        directory and then it will create AssetContainer there and imprint it
        with metadata. This will mark this path as container.

        Args:
            context (dict): application context
            name (str): Product name
            namespace (str): in Unreal this is basically path to container.
                             This is not passed here, so namespace is set
                             by `containerise()` because only then we know
                             real path.
            data (dict): Those would be data to be imprinted. This is not used
                         now, data are imprinted by `containerise()`.

        Returns:
            list(str): list of container content
        """

        # Create directory for asset and ayon container
        root = unreal_pipeline.AYON_ASSET_DIR
        folder_name = context["folder"]["name"]
        folder_path = context["folder"]["path"]
        product_type = context["product"]["productType"]
        suffix = "_CON"
        path = self.filepath_from_context(context)
        ext = os.path.splitext(path)[-1].lstrip(".")
        if folder_name:
            asset_name = "{}_{}_{}".format(folder_name, name, ext)
        else:
            asset_name = "{}_{}".format(name, ext)
        version = context["version"]["version"]
        # Check if version is hero version and use different name
        if version < 0:
            name_version = f"{name}_hero"
        else:
            name_version = f"{name}_v{version:03d}"

        tools = unreal.AssetToolsHelpers().get_asset_tools()
        asset_dir, container_name = tools.create_unique_asset_name(
            f"{root}/{folder_name}/{name_version}", suffix=f"_{ext}")

        container_name += suffix

        if not unreal.EditorAssetLibrary.does_directory_exist(asset_dir):
            unreal.EditorAssetLibrary.make_directory(asset_dir)
            loaded_options = {
                "abc_conversion_preset": options.get(
                    "abc_conversion_preset", self.abc_conversion_preset)
            }
            path = self.filepath_from_context(context)
            task = self.get_task(path, asset_dir, asset_name, False, loaded_options)

            asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
            asset_tools.import_asset_tasks([task])

            # Create Asset Container
            unreal_pipeline.create_container(
                container=container_name, path=asset_dir)

        data = {
            "schema": "ayon:container-2.0",
            "id": AYON_CONTAINER_ID,
            "folder_path": folder_path,
            "namespace": asset_dir,
            "container_name": container_name,
            "asset_name": asset_name,
            "loader": str(self.__class__.__name__),
            "representation": context["representation"]["id"],
            "parent": context["representation"]["versionId"],
            "product_type": product_type,
            # TODO these should be probably removed
            "asset": folder_path,
            "family": product_type,
        }
        unreal_pipeline.imprint(
            f"{asset_dir}/{container_name}", data)

        asset_content = unreal.EditorAssetLibrary.list_assets(
            asset_dir, recursive=True, include_folder=True
        )

        for a in asset_content:
            unreal.EditorAssetLibrary.save_asset(a)

        return asset_content

    def update(self, container, context):
        folder_name = container["asset_name"]
        repre_entity = context["representation"]
        source_path = get_representation_path(repre_entity)
        destination_path = container["namespace"]
        loaded_options = {
                "abc_conversion_preset": self.abc_conversion_preset
        }
        task = self.get_task(
            source_path, destination_path, folder_name, True, loaded_options
        )

        # do import fbx and replace existing data
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset_tools.import_asset_tasks([task])

        container_path = f"{container['namespace']}/{container['objectName']}"

        # update metadata
        unreal_pipeline.imprint(
            container_path,
            {
                "representation": repre_entity["id"],
                "parent": repre_entity["versionId"],
            })

        asset_content = unreal.EditorAssetLibrary.list_assets(
            destination_path, recursive=True, include_folder=True
        )

        for a in asset_content:
            unreal.EditorAssetLibrary.save_asset(a)

    def remove(self, container):
        path = container["namespace"]
        if unreal.EditorAssetLibrary.does_directory_exist(path):
            unreal.EditorAssetLibrary.delete_directory(path)
