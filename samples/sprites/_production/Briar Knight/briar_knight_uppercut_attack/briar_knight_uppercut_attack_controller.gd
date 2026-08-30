class_name BriarKnightUppercutAttackController
extends Node2D

signal damage_frame
signal attack_finished

@export var attack_sprite: AnimatedSprite2D
@export var sword_hitbox: Area2D

const ATTACK_ANIMATION := &"uppercut_attack"
const HIT_START_FRAME := 7
const HIT_END_FRAME := 8
const DAMAGE_EVENT_FRAME := 8
const ROOT_OFFSETS := PackedFloat32Array([
	0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
	0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
])

var _damage_emitted := false


func _ready() -> void:
	assert(attack_sprite != null, "Assign the Briar Knight AnimatedSprite2D.")
	attack_sprite.frame_changed.connect(_on_frame_changed)
	attack_sprite.animation_finished.connect(_on_animation_finished)
	_set_hitbox_active(false)


func play_uppercut_attack() -> void:
	_damage_emitted = false
	attack_sprite.position.x = 0.0
	_set_hitbox_active(false)
	attack_sprite.play(ATTACK_ANIMATION)


func _on_frame_changed() -> void:
	if attack_sprite.animation != ATTACK_ANIMATION:
		return
	var frame_index := clampi(attack_sprite.frame, 0, ROOT_OFFSETS.size() - 1)
	attack_sprite.position.x = ROOT_OFFSETS[frame_index]
	_set_hitbox_active(frame_index >= HIT_START_FRAME and frame_index <= HIT_END_FRAME)
	if frame_index == DAMAGE_EVENT_FRAME and not _damage_emitted:
		_damage_emitted = true
		damage_frame.emit()


func _on_animation_finished() -> void:
	if attack_sprite.animation != ATTACK_ANIMATION:
		return
	attack_sprite.position.x = 0.0
	_set_hitbox_active(false)
	attack_sprite.play(&"idle")
	attack_finished.emit()


func _set_hitbox_active(active: bool) -> void:
	if sword_hitbox == null:
		return
	sword_hitbox.set_deferred("monitoring", active)
	sword_hitbox.set_deferred("monitorable", active)
