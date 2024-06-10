# -*- coding: utf-8 -*-
"""Load FBX with animations."""
import json

from ayon_core.pipeline.context_tools import get_current_folder_entity
from ayon_core.pipeline import (
    get_representation_path,
    AYON_CONTAINER_ID
)
from ayon_unreal.api.plugin import UnrealBaseLoader
from ayon_unreal.api.pipeline import (
    send_request,
    containerise,
)


class AnimationFBXLoader(UnrealBaseLoader):
    """Load Unreal SkeletalMesh from FBX."""

    product_types = {"animation"}
    label = "Import FBX Animation"
    representations = {"fbx"}
    icon = "cube"
    color = "orange"

    @staticmethod
    def _import_fbx_task(
        filename, destination_path, destination_name, replace, automated,
        skeleton
    ):
        folder_entity = get_current_folder_entity(fields=["attrib.fps"])
        fps = folder_entity.get("attrib", {}).get("fps")

        options_properties = [
            ["automated_import_should_detect_type", "False"],
            ["original_import_type",
             "unreal.FBXImportType.FBXIT_SKELETAL_MESH"],
            ["mesh_type_to_import",
             "unreal.FBXImportType.FBXIT_ANIMATION"],
            ["import_mesh", "False"],
            ["import_animations", "True"],
            ["override_full_name", "True"],
            ["skeleton", f"get_asset({skeleton})"]
        ]

        sub_options_properties = [
            ["anim_sequence_import_data", "animation_length",
             "unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME"],
            ["anim_sequence_import_data",
             "import_meshes_in_bone_hierarchy", "False"],
            ["anim_sequence_import_data", "use_default_sample_rate", "False"],
            ["anim_sequence_import_data", "custom_sample_rate", str(fps)],
            ["anim_sequence_import_data", "import_custom_attribute", "True"],
            ["anim_sequence_import_data", "import_bone_tracks", "True"],
            ["anim_sequence_import_data", "remove_redundant_keys", "False"],
            ["anim_sequence_import_data", "convert_scene", "True"]
        ]

        params = {
            "filename": filename,
            "destination_path": destination_path,
            "destination_name": destination_name,
            "replace_existing": replace,
            "automated": automated,
            "save": True,
            "options_properties": options_properties,
            "sub_options_properties": sub_options_properties
        }

        send_request("import_fbx_task", params=params)

    def _process(self, asset_dir, asset_name, instance_name):
        automated = False
        actor = None
        skeleton = None

        if instance_name:
            automated = True
            actor, skeleton = send_request(
                "get_actor_and_skeleton",
                params={"instance_name": instance_name})

        if not actor:
            return None

        self._import_fbx_task(
            self.fname, asset_dir, asset_name, False, automated,
            skeleton)

        asset_content = send_request(
            "list_assets", params={
                "directory_path": asset_dir,
                "recursive": True,
                "include_folder": True})

        animation = None

        if animations := send_request(
            "get_assets_of_class",
            params={"asset_list": asset_content, "class_name": "AnimSequence"},
        ):
            animation = animations[0]

        if animation:
            send_request(
                "apply_animation_to_actor",
                params={
                    "actor_path": actor,
                    "animation_path": animation})

        return animation

    def load(self, context, name=None, namespace=None, options=None):
        """
        Load and containerise representation into Content Browser.

        This is two step process. First, import FBX to temporary path and
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
            options (dict): Those would be data to be imprinted. This is not
                            used now, data are imprinted by `containerise()`.
        """
        # Create directory for asset and Ayon container
        root = self.root
        folder_entity = context["folder"]
        folder_path = folder_entity["path"]
        hierarchy = folder_path.lstrip("/").split("/")

        folder_name = hierarchy.pop(-1)
        asset_name = f"{folder_name}_{name}" if folder_name else name

        asset_dir, container_name = send_request(
            "create_unique_asset_name", params={
                "root": root,
                "folder_name": folder_name,
                "name": name})

        master_level = send_request(
            "get_first_asset_of_class",
            params={
                "class_name": "World",
                "path": f"{root}/{hierarchy[0]}",
                "recursive": False})

        hierarchy_dir = root
        for h in hierarchy:
            hierarchy_dir = f"{hierarchy_dir}/{h}"
        hierarchy_dir = f"{hierarchy_dir}/{folder_name}"

        level = send_request(
            "get_first_asset_of_class",
            params={
                "class_name": "World",
                "path": f"{hierarchy_dir}/",
                "recursive": False})

        send_request("save_all_dirty_levels")
        send_request("load_level", params={"level_path": level})

        send_request("make_directory", params={"directory_path": asset_dir})

        libpath = self.fname.replace("fbx", "json")

        with open(libpath, "r") as fp:
            data = json.load(fp)

        instance_name = data.get("instance_name")

        animation = self._process(asset_dir, asset_name, instance_name)

        asset_content = send_request(
            "list_assets", params={
                "directory_path": hierarchy_dir,
                "recursive": True,
                "include_folder": False})

        # Get the sequence for the layout, excluding the camera one.
        all_sequences = send_request(
            "get_assets_of_class",
            params={
                "asset_list": asset_content,
                "class_name": "LevelSequence"})
        sequences = [
            a for a in all_sequences
            if "_camera" not in a.split("/")[-1]]

        send_request(
            "apply_animation",
            params={
                "animation_path": animation,
                "instance_name": instance_name,
                "sequences": sequences})

        product_type = context["product"]["productType"]

        data = {
            "schema": "ayon:container-2.0",
            "id": AYON_CONTAINER_ID,
            "namespace": asset_dir,
            "container_name": container_name,
            "asset_name": asset_name,
            "loader": str(self.__class__.__name__),
            "representation": str(context["representation"]["id"]),
            "parent": str(context["representation"]["versionId"]),
            "folder_path": folder_path,
            "product_type": product_type,
            # TODO these shold be probably removed
            "asset": folder_path,
            "family": product_type
        }
        containerise(asset_dir, container_name, data)

        send_request("save_current_level")
        send_request("load_level", params={"level_path": master_level})

        return send_request(
            "list_assets", params={
                "directory_path": asset_dir,
                "recursive": True,
                "include_folder": True})

    def update(self, container, context):
        asset_dir = container.get('namespace')
        repre_entity = context["representation"]
        asset_name = container["asset_name"]

        filename = get_representation_path(repre_entity)

        skeleton = send_request(
            "get_skeleton_from_skeletal_mesh",
            params={
                "skeletal_mesh_path": f"{asset_dir}/{asset_name}"})

        self._import_fbx_task(
            filename, asset_dir, asset_name, True, True, skeleton)

        super(UnrealBaseLoader, self).update(container, repre_entity)
