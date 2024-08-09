# -*- coding: utf-8 -*-
"""Load FBX with animations."""
import json
import os

import ayon_api
import unreal
from ayon_core.pipeline import (AYON_CONTAINER_ID, get_current_project_name,
                                get_representation_path)
from ayon_core.pipeline.context_tools import get_current_folder_entity
from ayon_core.pipeline.load import LoadError
from ayon_unreal.api import pipeline as unreal_pipeline
from ayon_unreal.api import plugin
from unreal import (EditorAssetLibrary, MovieSceneSkeletalAnimationSection,
                    MovieSceneSkeletalAnimationTrack)


class AnimationFBXLoader(plugin.Loader):
    """Load Unreal SkeletalMesh from FBX."""

    product_types = {"animation"}
    label = "Import FBX Animation"
    representations = {"fbx"}
    icon = "cube"
    color = "orange"

    show_dialog = False

    @classmethod  
    def apply_settings(cls, project_settings):  
        super(AnimationFBXLoader, cls).apply_settings(project_settings)  
        
        # Apply import settings  
        import_settings = (  
            project_settings.get("unreal", {}).get("import_settings", {})  
        )  

        cls.show_dialog = import_settings.get("show_dialog", 
                                                cls.show_dialog)   
    @classmethod
    def _import_animation(
        cls, self, path, asset_dir, asset_name, skeleton, automated, replace=False
    ):
        task = unreal.AssetImportTask()
        task.options = unreal.FbxImportUI()

        folder_entity = get_current_folder_entity(fields=["attrib.fps"])

        task.set_editor_property('filename', path)
        task.set_editor_property('destination_path', asset_dir)
        task.set_editor_property('destination_name', asset_name)
        task.set_editor_property('replace_existing', replace)
        task.set_editor_property('automated', not cls.show_dialog)
        task.set_editor_property('save', False)

        # set import options here
        task.options.set_editor_property(
            'automated_import_should_detect_type', True)
        task.options.set_editor_property(
            'original_import_type', unreal.FBXImportType.FBXIT_SKELETAL_MESH)
        task.options.set_editor_property(
            'mesh_type_to_import', unreal.FBXImportType.FBXIT_ANIMATION)
        task.options.set_editor_property('import_mesh', False)
        task.options.set_editor_property('import_animations', True)
        task.options.set_editor_property('override_full_name', True)
        task.options.set_editor_property('skeleton', skeleton)

        task.options.anim_sequence_import_data.set_editor_property(
            'animation_length',
            unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME
        )
        task.options.anim_sequence_import_data.set_editor_property(
            'import_meshes_in_bone_hierarchy', False)
        task.options.anim_sequence_import_data.set_editor_property(
            'use_default_sample_rate', False)
        task.options.anim_sequence_import_data.set_editor_property(
            'custom_sample_rate', folder_entity.get("attrib", {}).get("fps"))
        task.options.anim_sequence_import_data.set_editor_property(
            'import_custom_attribute', True)
        task.options.anim_sequence_import_data.set_editor_property(
            'import_bone_tracks', True)
        task.options.anim_sequence_import_data.set_editor_property(
            'remove_redundant_keys', False)
        task.options.anim_sequence_import_data.set_editor_property(
            'convert_scene', True)
        task.options.anim_sequence_import_data.set_editor_property(
            'force_front_x_axis', False)

        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    def _process(self, path, asset_dir, asset_name, instance_name):
        automated = False
        actor = None

        if instance_name:
            automated = True
            # Old method to get the actor
            # actor_name = 'PersistentLevel.' + instance_name
            # actor = unreal.EditorLevelLibrary.get_actor_reference(actor_name)
            actors = unreal.EditorLevelLibrary.get_all_level_actors()
            for a in actors:
                if a.get_class().get_name() != "SkeletalMeshActor":
                    continue
                if a.get_actor_label() == instance_name:
                    actor = a
                    break
            if not actor:
                raise LoadError(f"Could not find actor {instance_name}")
            skeleton = actor.skeletal_mesh_component.skeletal_mesh.skeleton

        if not actor:
            return None

        self._import_animation(
            path, asset_dir, asset_name, skeleton, automated)

        asset_content = EditorAssetLibrary.list_assets(
            asset_dir, recursive=True, include_folder=True
        )

        animation = None

        for a in asset_content:
            imported_asset_data = EditorAssetLibrary.find_asset_data(a)
            imported_asset = unreal.AssetRegistryHelpers.get_asset(
                imported_asset_data)
            if imported_asset.__class__ == unreal.AnimSequence:
                animation = imported_asset
                break

        if animation:
            animation.set_editor_property('enable_root_motion', True)
            actor.skeletal_mesh_component.set_editor_property(
                'animation_mode', unreal.AnimationMode.ANIMATION_SINGLE_NODE)
            actor.skeletal_mesh_component.animation_data.set_editor_property(
                'anim_to_play', animation)

        return animation

    def _load_from_json(
        self, libpath, path, asset_dir, asset_name, hierarchy_dir
    ):
        with open(libpath, "r") as fp:
            data = json.load(fp)

        instance_name = data.get("instance_name")

        animation = self._process(path, asset_dir, asset_name, instance_name)

        asset_content = EditorAssetLibrary.list_assets(
            hierarchy_dir, recursive=True, include_folder=False)

        # Get the sequence for the layout, excluding the camera one.
        sequences = [a for a in asset_content
                     if (EditorAssetLibrary.find_asset_data(a).get_class() ==
                         unreal.LevelSequence.static_class() and
                         "_camera" not in a.split("/")[-1])]

        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        for s in sequences:
            sequence = ar.get_asset_by_object_path(s).get_asset()
            possessables = [
                p for p in sequence.get_possessables()
                if p.get_display_name() == instance_name]

            for p in possessables:
                tracks = [
                    t for t in p.get_tracks()
                    if (t.get_class() ==
                        MovieSceneSkeletalAnimationTrack.static_class())]

                for t in tracks:
                    sections = [
                        s for s in t.get_sections()
                        if (s.get_class() ==
                            MovieSceneSkeletalAnimationSection.static_class())]

                    for s in sections:
                        s.params.set_editor_property('animation', animation)

    @staticmethod
    def is_skeleton(asset):
        return asset.get_class() == unreal.Skeleton.static_class()

    def _load_standalone_animation(
        self, path, asset_dir, asset_name, version_id
    ):
        selection = unreal.EditorUtilityLibrary.get_selected_assets()
        skeleton = None
        if selection:
            skeleton = selection[0]
            if not self.is_skeleton(skeleton):
                self.log.warning(
                    f"Selected asset {skeleton.get_name()} is not "
                    f"a skeleton. It is {skeleton.get_class().get_name()}")
                skeleton = None

        print("Trying to find original rig with links.")
        # If no skeleton is selected, we try to find the skeleton by
        # checking linked rigs.
        project_name = get_current_project_name()
        server = ayon_api.get_server_api_connection()

        v_links = server.get_version_links(
            project_name, version_id=version_id)
        entities = [v_link["entityId"] for v_link in v_links]
        linked_versions = list(server.get_versions(project_name, entities))

        rigs = [
            version["id"] for version in linked_versions
            if "rig" in version["attrib"]["families"]]

        self.log.debug(f"Found rigs: {rigs}")

        containers = unreal_pipeline.ls()

        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        for container in containers:
            self.log.debug(f"Checking container: {container}")
            if container["parent"] in rigs:
                # we found loaded version of the linked rigs
                namespace = container["namespace"]

                _filter = unreal.ARFilter(
                    class_names=["Skeleton"],
                    package_paths=[namespace],
                    recursive_paths=False)
                if skeletons := ar.get_assets(_filter):
                    skeleton = skeletons[0].get_asset()
                    break

        if not skeleton:
            raise LoadError("No skeleton found..")
        if not self.is_skeleton(skeleton):
            raise LoadError("Selected asset is not a skeleton.")

        self.log.info(f"Using skeleton: {skeleton.get_name()}")
        self._import_animation(
            path, asset_dir, asset_name, skeleton, True)

    def load(self, context, name, namespace, options=None):
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
            data (dict): Those would be data to be imprinted. This is not used
                         now, data are imprinted by `containerise()`.

        Returns:
            list(str): list of container content
        """
        # Create directory for asset and Ayon container
        root = "/Game/Ayon"
        folder_path = context["folder"]["path"]
        hierarchy = folder_path.lstrip("/").split("/")
        folder_name = hierarchy.pop(-1)
        product_type = context["product"]["productType"]

        suffix = "_CON"
        asset_name = f"{folder_name}_{name}" if folder_name else f"{name}"
        tools = unreal.AssetToolsHelpers().get_asset_tools()
        asset_dir, container_name = tools.create_unique_asset_name(
            f"{root}/Animations/{folder_name}/{name}", suffix="")

        path = self.filepath_from_context(context)
        libpath = path.replace(".fbx", ".json")

        master_level = None

        # check if json file exists.
        if os.path.exists(libpath):
            ar = unreal.AssetRegistryHelpers.get_asset_registry()

            _filter = unreal.ARFilter(
                class_names=["World"],
                package_paths=[f"{root}/{hierarchy[0]}"],
                recursive_paths=False)
            levels = ar.get_assets(_filter)
            master_level = levels[0].get_asset().get_path_name()

            hierarchy_dir = root
            for h in hierarchy:
                hierarchy_dir = f"{hierarchy_dir}/{h}"
            hierarchy_dir = f"{hierarchy_dir}/{folder_name}"

            _filter = unreal.ARFilter(
                class_names=["World"],
                package_paths=[f"{hierarchy_dir}/"],
                recursive_paths=True)
            levels = ar.get_assets(_filter)
            level = levels[0].get_asset().get_path_name()

            unreal.EditorLevelLibrary.save_all_dirty_levels()
            unreal.EditorLevelLibrary.load_level(level)

            container_name += suffix

            EditorAssetLibrary.make_directory(asset_dir)

            self._load_from_json(
                libpath, path, asset_dir, asset_name, hierarchy_dir)
        else:
            version_id = context["representation"]["versionId"]
            self._load_standalone_animation(
                path, asset_dir, asset_name, version_id)

        # Create Asset Container
        unreal_pipeline.create_container(
            container=container_name, path=asset_dir)

        data = {
            "schema": "ayon:container-2.0",
            "id": AYON_CONTAINER_ID,
            "namespace": asset_dir,
            "container_name": container_name,
            "asset_name": asset_name,
            "loader": str(self.__class__.__name__),
            "representation": context["representation"]["id"],
            "parent": context["representation"]["versionId"],
            "folder_path": folder_path,
            "product_type": product_type,
            # TODO these shold be probably removed
            "asset": folder_path,
            "family": product_type
        }
        unreal_pipeline.imprint(f"{asset_dir}/{container_name}", data)

        imported_content = EditorAssetLibrary.list_assets(
            asset_dir, recursive=True, include_folder=False)

        for asset in imported_content:
            loaded_asset = EditorAssetLibrary.load_asset(asset)
            # Enable root motion for animations so they are oriented correctly
            if loaded_asset.get_class() == unreal.AnimSequence.static_class():
                loaded_asset.set_editor_property("enable_root_motion", True)
                loaded_asset.set_editor_property(
                    "root_motion_root_lock",
                    unreal.RootMotionRootLock.ANIM_FIRST_FRAME)
            EditorAssetLibrary.save_asset(asset)

        if master_level:
            unreal.EditorLevelLibrary.save_current_level()
            unreal.EditorLevelLibrary.load_level(master_level)

    def update(self, container, context):
        repre_entity = context["representation"]
        folder_name = container["asset_name"]
        source_path = get_representation_path(repre_entity)
        destination_path = container["namespace"]

        skeletal_mesh = EditorAssetLibrary.load_asset(
            container.get('namespace') + "/" + container.get('asset_name'))
        skeleton = skeletal_mesh.get_editor_property('skeleton')

        self._import_animation(
            source_path, destination_path, folder_name, skeleton, True, True)

        container_path = f'{container["namespace"]}/{container["objectName"]}'
        # update metadata
        unreal_pipeline.imprint(
            container_path,
            {
                "representation": repre_entity["id"],
                "parent": repre_entity["versionId"],
            })

        asset_content = EditorAssetLibrary.list_assets(
            destination_path, recursive=True, include_folder=True
        )

        for a in asset_content:
            EditorAssetLibrary.save_asset(a)

    def remove(self, container):
        path = container["namespace"]
        parent_path = os.path.dirname(path)

        EditorAssetLibrary.delete_directory(path)

        asset_content = EditorAssetLibrary.list_assets(
            parent_path, recursive=False, include_folder=True
        )

        if len(asset_content) == 0:
            EditorAssetLibrary.delete_directory(parent_path)
